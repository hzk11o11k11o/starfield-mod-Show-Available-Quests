#include "PCH.h"

#include "SAQ_UI.h"

#include "RE/B/BSFixedString.h"
#include "RE/I/IMenu.h"
// 注意 include 顺序：ASMovieRootBase.h 不自包含（Value/Movie/FunctionHandler 都要先有），
// 顺序错了会报 C4430/C2061 一连串语法错误（见 docs/01 坑 1）。
#include "RE/S/ScaleformGFxMovie.h"
#include "RE/S/ScaleformGFxValue.h"
#include "RE/S/ScaleformGFxFunctionHandler.h"
#include "RE/S/ScaleformGFxASMovieRootBase.h"
#include "RE/U/UI.h"

#include <Windows.h>

#include <atomic>
#include <cstdio>
#include <cstring>
#include <format>
#include <memory>
#include <string>
#include <utility>

namespace SAQ::UI
{
	namespace
	{
		// ====================================================================
		// 一、偏移常量（★ 1.16.244.0 反汇编实测，不要照抄 commonlibsf）
		//
		// 证据：Starfield.exe 里 UI::IsMenuOpen（Address Library ID 130475，
		// RVA 0x2544D60）：
		//     lea  rcx, [rbp + 0x450]     ; rbp = UI*
		//     mov  rdx, rsi               ; const BSFixedString&（菜单名）
		//     lea  r8,  [rsp + 0x20]      ; 输出
		//     call 0x142546170            ; 散列表查找
		//     mov  rcx, [rsp + 0x40]      ; = 值 + 0x20
		//     test al, al / test rcx, rcx / setne bl   ; 非空 ⇒ 菜单是开着的
		//
		// 查找函数（RVA 0x2546170）读的表字段：
		//     mov  rbx, [rcx + 0x40]         ; 容量（2 的幂）
		//     mov  rcx, [rbp + 0x38]         ; 条目数组指针
		//     imul rax, rdx, 0x38            ; 条目跨度 0x38
		//     cmp  dword [rax+rcx+0x30], -1  ; 空槽哨兵
		//     cmp  qword [rax+rcx], rsi      ; key = string-pool 指针（指针相等比较）
		// 哈希 = keyPtr ^ (keyPtr >> 32)（与 commonlibsf 的 UIMenuNameHash 一致）。
		//
		// 结论：
		//   ★ 真实的菜单表在 UI+0x450，而 commonlibsf 的 UI::menuMap 标的是 0x470
		//     —— 用 UI::GetMenuMovie() 在 1.16.244.0 上永远查不到（本轮 bug 的根因）。
		//   * 表头：条目数组 @+0x38、容量 @+0x40；条目 0x38 字节：
		//     key @+0x00、值 @+0x08（0x28 字节）、nextIndex @+0x30（-1 = 空槽）。
		//   * 值的 +0x20 是 Ptr<IMenu>（IsMenuOpen 就是查它非空）。
		// ====================================================================
		constexpr std::size_t kMenuMapOffset = 0x450;
		constexpr std::size_t kMapEntriesOffset = 0x38;
		constexpr std::size_t kMapCapacityOffset = 0x40;
		constexpr std::size_t kEntryStride = 0x38;
		constexpr std::size_t kEntryValueOffset = 0x08;
		constexpr std::size_t kEntryNextOffset = 0x30;
		constexpr std::size_t kMenuPtrInValueOffset = 0x20;

		// commonlibsf 的 IMenu / Movie 成员偏移（下面每次都会拿 RTTI 名字复核，
		// 对不上就换候选偏移，所以这里错也不会炸）。
		constexpr std::size_t kIMenuUiMovieOffset = 0x088;
		constexpr std::size_t kMovieAsRootOffset = 0x010;

		// commonlibsf 的 ASMovieRootBase 虚函数槽（只调这两个，且调用前都会核对槽指向主模块）
		constexpr std::size_t kSlotAsRootCreateString = 0x2C;  // CreateString(Value*, const char*)
		constexpr std::size_t kSlotAsRootInvoke = 0x39;        // Invoke(const char*, Value*, const Value*, u32)

		constexpr const char* kMenuName = "BSMissionMenu";

		// ====================================================================
		// 二、安全内存访问
		//
		// 本文件大量「按猜出来的偏移读内存」，所以每一步都包在 SEH 里：
		// 猜错最多返回失败，不会把游戏带崩。
		// ====================================================================

		std::uintptr_t ModuleBase()
		{
			static const std::uintptr_t base = reinterpret_cast<std::uintptr_t>(::GetModuleHandleW(nullptr));
			return base;
		}

		std::size_t ModuleSize()
		{
			static const std::size_t size = [] {
				const auto base = ModuleBase();
				const auto* dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(base);
				if (!base || dos->e_magic != IMAGE_DOS_SIGNATURE) {
					return std::size_t{ 0x8000000 };
				}
				const auto* nt = reinterpret_cast<const IMAGE_NT_HEADERS64*>(base + static_cast<std::uintptr_t>(dos->e_lfanew));
				return static_cast<std::size_t>(nt->OptionalHeader.SizeOfImage);
			}();
			return size;
		}

		bool IsMapped(const void* a_ptr, std::size_t a_bytes)
		{
			if (!a_ptr) {
				return false;
			}
			MEMORY_BASIC_INFORMATION mbi{};
			if (::VirtualQuery(a_ptr, &mbi, sizeof(mbi)) == 0) {
				return false;
			}
			if (mbi.State != MEM_COMMIT) {
				return false;
			}
			if ((mbi.Protect & PAGE_GUARD) != 0 || (mbi.Protect & PAGE_NOACCESS) != 0) {
				return false;
			}
			const auto begin = reinterpret_cast<std::uintptr_t>(a_ptr);
			const auto end = reinterpret_cast<std::uintptr_t>(mbi.BaseAddress) + mbi.RegionSize;
			return begin <= end && a_bytes <= end - begin;
		}

		template <class T>
		T SafeRead(const void* a_src, T a_fallback)
		{
			if (!IsMapped(a_src, sizeof(T))) {
				return a_fallback;
			}
			__try {
				return *static_cast<const T*>(a_src);
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				return a_fallback;
			}
		}

		std::uintptr_t ReadPtr(std::uintptr_t a_at)
		{
			return SafeRead<std::uintptr_t>(reinterpret_cast<const void*>(a_at), 0);
		}

		// 对象 → 虚表 →（x64 的 -8 处）COL → TypeDescriptor → 修饰名。
		// 用来确认「这个指针真的是 Movie / MovieRoot」这类判断，比猜偏移可靠得多。
		bool SafeRttiName(const void* a_obj, char (&a_out)[192])
		{
			a_out[0] = '\0';
			__try {
				const auto vtable = *reinterpret_cast<const std::uintptr_t* const*>(a_obj);
				const auto col = *reinterpret_cast<const std::uintptr_t*>(
					reinterpret_cast<const std::byte*>(vtable) - sizeof(std::uintptr_t));
				const auto tdRva = *reinterpret_cast<const std::int32_t*>(
					reinterpret_cast<const std::byte*>(col) + 0x0C);
				const auto td = ModuleBase() + static_cast<std::uintptr_t>(static_cast<std::uint32_t>(tdRva));
				const auto* name = reinterpret_cast<const char*>(td + 0x10);  // MSVC：TD 的名字在 +0x10
				for (std::size_t i = 0; i + 1 < sizeof(a_out); ++i) {
					a_out[i] = name[i];
					if (name[i] == '\0') {
						return true;
					}
				}
				a_out[sizeof(a_out) - 1] = '\0';
				return true;
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				a_out[0] = '\0';
				return false;
			}
		}

		// 这个对象里有没有某个 qword 正好等于 a_value（前 a_scanBytes 字节内）。
		//
		// 用来确认「菜单表条目里的这个指针确实指向 BSMissionMenu 那个 IMenu」：
		// IMenu 里存着自己的 menuName（BSFixedString），而 string pool 是**唯一化**的，
		// 所以它和表里的 key 是同一个指针 —— 指针相等就说明身份对上了。
		// 好处是**完全不需要知道 menuName 在 IMenu 里的偏移**（偏移变了也照样管用）。
		bool ObjectContainsPointer(const void* a_obj, std::uintptr_t a_value, std::size_t a_scanBytes)
		{
			if (!a_obj || !a_value) {
				return false;
			}
			__try {
				const auto* bytes = static_cast<const std::byte*>(a_obj);
				for (std::size_t off = 0; off + sizeof(std::uintptr_t) <= a_scanBytes; off += sizeof(std::uintptr_t)) {
					if (*reinterpret_cast<const std::uintptr_t*>(bytes + off) == a_value) {
						return true;
					}
				}
				return false;
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				return false;
			}
		}

		// 虚表槽指向主模块的可执行段吗（调用前的最后一道廉价保险）
		bool VtableSlotInModule(const void* a_obj, std::size_t a_slot)
		{
			__try {
				const auto vtable = *reinterpret_cast<const std::uintptr_t* const*>(a_obj);
				const auto fn = vtable[a_slot];
				return fn >= ModuleBase() && fn < ModuleBase() + ModuleSize();
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				return false;
			}
		}

		// ====================================================================
		// 三、菜单表查找（算法的照抄实现，见文件顶部注释）
		// ====================================================================

		// 返回指向「条目里的值」的指针；查不到返回 nullptr。
		std::uintptr_t ScatterFindValue(std::uintptr_t a_map, std::uintptr_t a_key)
		{
			if (!a_map || !a_key) {
				return 0;
			}
			__try {
				const auto* map = reinterpret_cast<const std::byte*>(a_map);
				const auto capacity = *reinterpret_cast<const std::uint64_t*>(map + kMapCapacityOffset);
				const auto* entries = *reinterpret_cast<const std::byte* const*>(map + kMapEntriesOffset);
				if (!entries || capacity < 2 || capacity > 0x20000 || (capacity & (capacity - 1)) != 0) {
					return 0;  // 形状不对 ⇒ 这不是菜单表
				}
				std::uint64_t index = (a_key ^ (a_key >> 32)) & (capacity - 1);
				for (std::uint32_t guard = 0; guard < 0x40; ++guard) {
					const auto* entry = entries + index * kEntryStride;
					const auto next = *reinterpret_cast<const std::int32_t*>(entry + kEntryNextOffset);
					if (next == -1) {
						return 0;  // 空槽 ⇒ 查不到
					}
					if (*reinterpret_cast<const std::uintptr_t*>(entry) == a_key) {
						return reinterpret_cast<std::uintptr_t>(entry + kEntryValueOffset);
					}
					index = static_cast<std::uint64_t>(static_cast<std::uint32_t>(next));
					if (index >= capacity) {
						return 0;
					}
				}
				return 0;
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				return 0;
			}
		}

		// ====================================================================
		// 四、解析缓存
		// ====================================================================

		struct Bridge
		{
			bool           ok{ false };
			std::uintptr_t menu{};      // IMenu*
			std::uintptr_t movie{};     // Scaleform::GFx::Movie*
			std::uintptr_t asRoot{};    // ASMovieRootBase*
			std::size_t    mapOffset{ kMenuMapOffset };
			std::size_t    menuInValueOffset{ kMenuPtrInValueOffset };
			std::size_t    uiMovieOffset{ kIMenuUiMovieOffset };
			std::size_t    asRootOffset{ kMovieAsRootOffset };
			char           menuName[64]{};
			char           movieRtti[192]{};
			char           rootRtti[192]{};
			std::string    detail;
		};

		Bridge& Cached()
		{
			static Bridge bridge;
			return bridge;
		}

		// 候选偏移的试探顺序：先试反汇编实测值，再按 8 字节步长扫一遍附近
		// （万一以后游戏更新把某个成员挪了，这一层还能自救）。
		template <class Fn>
		void ForEachCandidate(std::size_t a_first, std::size_t a_last, std::size_t a_step, Fn&& a_fn)
		{
			for (std::size_t off = a_first; off <= a_last; off += a_step) {
				if (a_fn(off)) {
					return;
				}
			}
		}

		bool ResolveMapAndMenu(RE::UI* a_ui, Bridge& a_out)
		{
			// 菜单名的 key 就是 BSFixedString 里的 string-pool 指针（见 docs/02）：
			// 表里存的和查询用的都是它，比较也是指针比较。
			static const RE::BSFixedString menuName{ kMenuName };
			const auto key = *reinterpret_cast<const std::uintptr_t*>(std::addressof(menuName));
			if (!key) {
				a_out.detail = "BSFixedString(\"BSMissionMenu\") 未进入 string pool";
				return false;
			}

			const auto uiBase = reinterpret_cast<std::uintptr_t>(a_ui);

			bool found = false;
			ForEachCandidate(0x3C0, 0x4C0, 8, [&](std::size_t mapOffset) {
				const auto value = ScatterFindValue(uiBase + mapOffset, key);
				if (!value) {
					return false;
				}
				// 值里哪个 qword 是 IMenu*？先用 IsMenuOpen 的实测偏移 0x20，再扫 0x00~0x20，
				// 判据 = 那个对象里存着自己的 menuName（同一个 string-pool 指针）。
				bool hit = false;
				ForEachCandidate(0, 0x20, 8, [&](std::size_t inValueOffset) {
					const auto menu = ReadPtr(value + inValueOffset);
					if (!menu) {
						return false;
					}
					if (!ObjectContainsPointer(reinterpret_cast<const void*>(menu), key, 0x200)) {
						return false;
					}
					a_out.mapOffset = mapOffset;
					a_out.menuInValueOffset = inValueOffset;
					a_out.menu = menu;
					std::memcpy(a_out.menuName, kMenuName, sizeof(kMenuName));
					hit = true;
					return true;
				});
				if (hit) {
					found = true;
				}
				return hit;
			});

			if (!found) {
				a_out.detail = "UI 里没找到 BSMissionMenu 的菜单表条目";
				return false;
			}
			return true;
		}

		// 弱判据（RTTI 名字读不出来时的兜底）：对象首 qword 看起来是主模块里的代码指针。
		bool LooksLikeVmObject(std::uintptr_t a_obj)
		{
			const auto vtable = ReadPtr(a_obj);
			return vtable >= ModuleBase() && vtable < ModuleBase() + ModuleSize();
		}

		bool ResolveMovie(Bridge& a_out)
		{
			// IMenu::uiMovie（Ptr<Movie>）：
			//   ① 0x80~0x140 里找「RTTI 名字含 Movie（但不是 MovieDef）」的指针；
			//   ② 全不中时，退回 commonlibsf 的偏移 0x88 + 弱判据（只试这一个偏移，避免误判）。
			bool found = false;
			ForEachCandidate(0x80, 0x140, 8, [&](std::size_t offset) {
				const auto candidate = ReadPtr(a_out.menu + offset);
				if (!candidate) {
					return false;
				}
				char rtti[192]{};
				if (!SafeRttiName(reinterpret_cast<const void*>(candidate), rtti) || !rtti[0]) {
					return false;
				}
				if (!std::strstr(rtti, "Movie") || std::strstr(rtti, "MovieDef")) {
					return false;
				}
				a_out.uiMovieOffset = offset;
				a_out.movie = candidate;
				std::memcpy(a_out.movieRtti, rtti, sizeof(a_out.movieRtti));
				found = true;
				return true;
			});

			if (!found && LooksLikeVmObject(ReadPtr(a_out.menu + kIMenuUiMovieOffset))) {
				a_out.uiMovieOffset = kIMenuUiMovieOffset;
				a_out.movie = ReadPtr(a_out.menu + kIMenuUiMovieOffset);
				std::snprintf(a_out.movieRtti, sizeof(a_out.movieRtti), "弱判据(无RTTI)");
				found = true;
			}

			if (!found) {
				a_out.detail = "IMenu 里没找到 Movie 指针（0x80~0x140 + 0x88 兜底都没中）";
				return false;
			}
			return true;
		}

		bool ResolveAsRoot(Bridge& a_out)
		{
			// Movie::asMovieRoot（Ptr<ASMovieRootBase>）：
			//   ① 0x00~0x40 里找「RTTI 名字含 MovieRoot」的指针；
			//   ② 全不中时退回 commonlibsf 的 0x10 + 弱判据。
			bool found = false;
			ForEachCandidate(0x00, 0x40, 8, [&](std::size_t offset) {
				const auto candidate = ReadPtr(a_out.movie + offset);
				if (!candidate) {
					return false;
				}
				char rtti[192]{};
				if (!SafeRttiName(reinterpret_cast<const void*>(candidate), rtti) || !rtti[0]) {
					return false;
				}
				if (!std::strstr(rtti, "MovieRoot")) {
					return false;
				}
				a_out.asRootOffset = offset;
				a_out.asRoot = candidate;
				std::memcpy(a_out.rootRtti, rtti, sizeof(a_out.rootRtti));
				found = true;
				return true;
			});

			if (!found && LooksLikeVmObject(ReadPtr(a_out.movie + kMovieAsRootOffset))) {
				a_out.asRootOffset = kMovieAsRootOffset;
				a_out.asRoot = ReadPtr(a_out.movie + kMovieAsRootOffset);
				std::snprintf(a_out.rootRtti, sizeof(a_out.rootRtti), "弱判据(无RTTI)");
				found = true;
			}

			if (!found) {
				a_out.detail = "Movie 里没找到 ASMovieRoot 指针（0x00~0x40 + 0x10 兜底都没中）";
				return false;
			}
			return true;
		}

		// 真正调用 ASMovieRoot::Invoke 的地方。
		// 注意：带 __try 的函数里不能有「需要栈展开的对象」（MSVC C2712），
		// 所以这一层只收裸指针、不碰 std::string/wstring。
		bool SafeInvoke(RE::Scaleform::GFx::ASMovieRootBase* a_root, const char* a_path,
			RE::Scaleform::GFx::Value* a_result, RE::Scaleform::GFx::Value* a_args, std::uint32_t a_count)
		{
			__try {
				return a_root->Invoke(a_path, a_result, a_args, a_count);
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				return false;
			}
		}

		std::string Describe(const Bridge& a_bridge)
		{
			std::string s;
			s += "菜单表=UI+0x";
			s += std::format("{:X}", a_bridge.mapOffset);
			s += " IMenu=值+0x";
			s += std::format("{:X}", a_bridge.menuInValueOffset);
			s += " uiMovie=IMenu+0x";
			s += std::format("{:X}", a_bridge.uiMovieOffset);
			s += "(" + std::string(a_bridge.movieRtti) + ")";
			s += " asMovieRoot=Movie+0x";
			s += std::format("{:X}", a_bridge.asRootOffset);
			s += "(" + std::string(a_bridge.rootRtti) + ")";
			return s;
		}
	}

	bool EnsureResolved(std::string& a_detail)
	{
		auto& bridge = Cached();
		if (bridge.ok) {
			a_detail = bridge.detail;
			return true;
		}

		auto* ui = RE::UI::GetSingleton();
		if (!ui) {
			a_detail = "UI 单例不可用";
			return false;
		}

		if (!ResolveMapAndMenu(ui, bridge)) {
			a_detail = bridge.detail.empty() ? std::string{ "菜单表解析失败" } : bridge.detail;
			bridge.detail.clear();
			return false;
		}
		if (!ResolveMovie(bridge)) {
			a_detail = bridge.detail;
			bridge.detail.clear();
			return false;
		}
		if (!ResolveAsRoot(bridge)) {
			a_detail = bridge.detail;
			bridge.detail.clear();
			return false;
		}

		bridge.ok = true;
		bridge.detail = Describe(bridge);
		a_detail = bridge.detail;
		return true;
	}

	namespace
	{
		// 把任务列表编成一行行文本（AS3 侧解析，协议见 docs/02-UI通道逆向.md）：
		//     SAQ1
		//     T\t<tab 标题>
		//     Q\t<FormID>\t<type>\t<显示名>
		// 名字里可能有任意标点，所以用 Tab 分隔、名字放最后一项。
		std::string BuildPayloadUtf8(const std::vector<QuestEntry>& a_quests, std::string_view a_tabText)
		{
			std::string s;
			s.reserve(a_quests.size() * 32 + 64);
			s += "SAQ1\n";
			s += "T\t";
			s += a_tabText;
			s += "\n";
			for (const auto& q : a_quests) {
				std::string name = q.name;
				for (auto& ch : name) {
					if (ch == '\r' || ch == '\n' || ch == '\t') {
						ch = ' ';
					}
				}
				s += "Q\t";
				s += std::to_string(q.formID);
				s += "\t";
				s += std::to_string(q.type);
				s += "\t";
				s += name;
				s += "\n";
			}
			return s;
		}

		std::wstring Utf8ToWide(std::string_view a_utf8)
		{
			if (a_utf8.empty()) {
				return {};
			}
			const int need = ::MultiByteToWideChar(CP_UTF8, 0, a_utf8.data(),
				static_cast<int>(a_utf8.size()), nullptr, 0);
			if (need <= 0) {
				return {};
			}
			std::wstring out(static_cast<std::size_t>(need), L'\0');
			::MultiByteToWideChar(CP_UTF8, 0, a_utf8.data(), static_cast<int>(a_utf8.size()),
				out.data(), need);
			return out;
		}

		bool SafeCreateString(RE::Scaleform::GFx::ASMovieRootBase* a_root, RE::Scaleform::GFx::Value* a_out, const char* a_utf8)
		{
			__try {
				a_root->CreateString(a_out, a_utf8);
				return true;
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				return false;
			}
		}

		// 一次尝试 = 一种「参数编码」× 一种「函数路径」。
		// 数组参数那一版已经废掉了（要 CreateArray/CreateObject/PushBack 三个 vfunc 槽，
		// 槽号猜错的风险比字符串大得多），统一走「一整个字符串 + AS3 侧自己解析」。
		struct Attempt
		{
			bool        wide;  // true = 宽字符 Value（UTF-16）；false = CreateString(UTF-8)
			const char* path;
		};
		constexpr Attempt kAttempts[] = {
			{ true, "SetAvailableQuests" },
			{ true, "_root.SetAvailableQuests" },
			{ true, "_root.root.SetAvailableQuests" },
			{ false, "SetAvailableQuests" },
			{ false, "_root.SetAvailableQuests" },
			{ false, "_root.root.SetAvailableQuests" },
		};
	}

	bool PushAvailableQuests(const std::vector<QuestEntry>& a_quests, std::string_view a_tabText, std::string& a_detail)
	{
		if (!EnsureResolved(a_detail)) {
			return false;
		}
		auto& bridge = Cached();
		auto* root = reinterpret_cast<RE::Scaleform::GFx::ASMovieRootBase*>(bridge.asRoot);
		if (!root) {
			a_detail = "ASMovieRoot 指针为空";
			return false;
		}
		if (!VtableSlotInModule(root, kSlotAsRootInvoke)) {
			a_detail = "ASMovieRoot 的 Invoke 槽不在主模块里（vtable 布局对不上）";
			return false;
		}

		const std::string payloadUtf8 = BuildPayloadUtf8(a_quests, a_tabText);
		const std::wstring payloadWide = Utf8ToWide(payloadUtf8);
		if (payloadWide.empty()) {
			a_detail = "载荷编码失败（UTF-8 -> UTF-16）";
			return false;
		}

		bool ok = false;
		std::string trail;
		for (const auto& attempt : kAttempts) {
			RE::Scaleform::GFx::Value args[1];
			bool argReady = false;
			if (attempt.wide) {
				args[0] = RE::Scaleform::GFx::Value(payloadWide.c_str());  // kStringW：UTF-16，中文不过编码转换
				argReady = true;
			} else if (VtableSlotInModule(root, kSlotAsRootCreateString)) {
				argReady = SafeCreateString(root, &args[0], payloadUtf8.c_str());  // utf8 -> 托管字符串
			}
			if (!argReady) {
				trail += std::string{ trail.empty() ? "" : " | " } + attempt.path + "=arg失败";
				continue;
			}

			RE::Scaleform::GFx::Value ret;
			const bool called = SafeInvoke(root, attempt.path, &ret, args, 1);

			double reported = -1.0;
			bool hasNumber = false;
			if (called && (ret.IsNumber() || ret.IsInt() || ret.IsUInt())) {
				reported = ret.GetNumber();
				hasNumber = true;
			}

			trail += std::string{ trail.empty() ? "" : " | " } + (attempt.wide ? "W:" : "S:") + attempt.path;
			trail += called ? "=ok" : "=fail";
			if (hasNumber) {
				trail += "(" + std::format("{:.0f}", reported) + ")";
			}

			// AS3 侧返回「实际拿到多少条」；0 = 字符串没解析出来（编码/传参不对），继续试下一种。
			if (called && reported > 0.0) {
				ok = true;
				break;
			}
		}

		a_detail = bridge.detail + " 调用: " + trail + std::format(" 载荷={} 字节/{} 条", payloadUtf8.size(), a_quests.size());
		return ok;
	}
}
