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
		// 查找函数（RVA 0x2546170）的**逐条真身**（2026-09-19 第 3 轮重新反汇编）：
		//     mov  rbx, [rcx + 0x40]         ; 容量（2 的幂）
		//     mov  rsi, [rdx]                ; key = BSFixedString 里那唯一的 qword（= Entry*）
		//     mov  eax, [rsi + 0x14]         ; ★ 读 string-pool Entry 的 flags
		//     shr  eax, 1 / test al, 1       ;   kExternal(=1<<1) 位
		//     je   →  lea rcx, [rsi + 0x18]  ;   ✦ 普通条目：字符数据 = Entry + 0x18
		//     jne  →  mov rcx, [rsi + 8]     ;   ✦ 外挂条目：沿 _right 找到叶子（函数 0x28CAE80）
		//     mov  rax, rcx / shr rax, 0x20 / xor ecx, eax
		//                                    ; ★★ 哈希 = charsPtr ^ (charsPtr >> 32)
		//     and  rdx, [rbx - 1]            ; index = hash & (capacity - 1)
		//     mov  rcx, [rbp + 0x38]         ; 条目数组指针
		//     imul rax, rdx, 0x38            ; 条目跨度 0x38
		//     cmp  dword [rax+rcx+0x30], -1  ; 空槽哨兵
		//     cmp  qword [rax+rcx], rsi      ; ★ key 的**比较**用的是 Entry*（不是 chars）
		//
		// ★ 这里有两个**不同的**指针，第 3 轮就是把它俩搞混才一直失败的：
		//     entryKey = BSFixedString 里的 Entry*  → 只用于**比较**
		//     charsPtr = Entry 的字符数据(+0x18)    → 只用于**算哈希**
		//   commonlibsf 的 `UIMenuNameHash` 写的是 `c_str()` 的指针…但那个 `c_str()`
		//   返回的就是字符指针，我们上一轮却拿 Entry* 去算哈希 ⇒ 每次都在错的桶里找，
		//   链一走到空槽就报「没找到」——就是 `UI 里没找到 BSMissionMenu 的菜单表条目`
		//   的真凶（日志实测：UI 指针、IsMenuOpen 都是好的，只有我们自己查表查不到）。
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

		// commonlibsf 的 IMenu 成员偏移。
		//
		// ★ 2026-09-19 第 5 轮：这套偏移这次**被运行时证据反证了**（不是猜的）：
		//   上一轮日志里 `uiMovie=IMenu+0x78(?AVMovieClip@fl_display@Instances@AS3@GFx@Scaleform@@)`
		//   —— 0x78 上是个 AS3 的 MovieClip 实例对象，而它正好等于
		//   `menuObj(0x58) + Value::_value(0x20)`。GFx::Value 的布局
		//   （_prev 00 / _next 08 / _objectInterface 10 / _type 18 / _value 20，sizeof 0x30）
		//   由 commonlibsf 声明，且被这次观测独立印证 ⇒ IMenu::menuObj 确实在 0x58。
		//   于是：
		//     IMenu+0x58  menuObj（GFx::Value，装的是菜单根 AS3 对象）
		//     IMenu+0x68  = menuObj._objectInterface（GFx::Value::ObjectInterface*）
		//     IMenu+0x78  = menuObj._value（AS3 根对象本体，上一轮误当成 Movie 的那个）
		//     IMenu+0x88  = uiMovie（commonlibsf 声明，紧跟在 Value 后面）
		constexpr std::size_t kIMenuMenuObjOffset = 0x058;
		constexpr std::size_t kValueObjectInterfaceOffset = 0x010;
		constexpr std::size_t kValueDataOffset = 0x020;
		constexpr std::size_t kIMenuUiMovieOffset = 0x088;

		// GFx::Value::ObjectInterface 的成员（commonlibsf 声明，与 GFx SDK 一致）：
		//   +0x00 虚表 / +0x08 MovieImpl* movieRoot / +0x10 Value* lastValue
		// ⇒ 「电影对象」还有一条**不依赖 IMenu 偏移**的取法：
		//     MovieImpl* = [[IMenu + 0x68] + 0x08]
		constexpr std::size_t kObjectInterfaceMovieRootOffset = 0x008;

		// ★ 精确身份判据（离线从 exe 的 RTTI 里量出来的主虚表 RVA）
		//   tools/re/rtti_slots.py --name "MovieRoot@AS3@GFx@Scaleform@@"
		//     TD RVA 0x59A53C0  主 vtable RVA 0x3BE32B0
		//     [2C] CreateString / [2D] CreateStringW / [38] / [39] Invoke=0x3368DC0 / [3A] InvokeArgs
		//   tools/re/rtti_slots.py --name "MovieImpl@GFx@Scaleform@@"
		//     TD RVA 0x599B150  主 vtable RVA 0x3BCFEE8
		//
		//   为什么要「比对虚表 RVA」而不是「比对 RTTI 名字」：RTTI 名字要读
		//   vtable[-1] → COL → TD → 名字，中途任何一步失败就退化成"没有 RTTI"，
		//   上一轮就是靠"名字里含 Movie"这种模糊判据把 AS3 的 MovieClip 当成 Movie 了。
		//   虚表 RVA 是**一次指针比较**，全 exe 唯一，误判概率为零。
		constexpr std::uintptr_t kMovieRootVtableRva = 0x3BE32B0;
		constexpr std::uintptr_t kMovieImplVtableRva = 0x3BCFEE8;

		// ASMovieRootBase 虚函数槽（**槽序号**，不是字节偏移）：
		//   vtable[0x31] = SetVariable(const char*, const Value&, SetVarType)
		//   vtable[0x39] = Invoke(const char*, Value*, const Value*, u32)
		constexpr std::size_t kSlotAsRootCreateString = 0x2C;  // CreateString(Value*, const char*)
		constexpr std::size_t kSlotAsRootSetVariable = 0x31;   // SetVariable(const char*, const Value&)
		constexpr std::size_t kSlotAsRootInvoke = 0x39;        // Invoke(const char*, Value*, const Value*, u32)
		constexpr std::uintptr_t kInvokeRva = 0x3368DC0;       // 上面那个槽指向的函数（1.16.244.0 实测）

		// 在「电影对象」里扫 ASMovieRoot 指针时扫多少字节。
		// （MovieImpl 里存 ASMovieRoot 的位置没挖（也无需挖）：按虚表比对比扫一遍更快也更稳，
		//   实测一次菜单打开只扫一次，2048 次指针读取，无感。）
		constexpr std::size_t kMovieScanBytes = 0x4000;
		constexpr std::size_t kObjectScanBytes = 0x800;

		constexpr const char* kMenuName = "BSMissionMenu";

		// 新 tab 的标题（中/英各一份推给 AS3，由 AS3 按游戏语言挑）
		constexpr std::string_view kTabTitleZh = "可接任务";
		constexpr std::string_view kTabTitleEn = "Available";

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

		// 调用前核对 ASMovieRoot::Invoke 的虚表槽：拿到它的 RVA 用来比对离线验证值。
		// 返回 false = 槽指针不落在主模块里（vtable 布局对不上 ⇒ 宁可失败也不能乱调）。
		bool CheckInvokeSlot(std::uintptr_t a_root, std::uintptr_t& a_outRva, std::string& a_detail)
		{
			const auto vtable = ReadPtr(a_root);
			if (!vtable) {
				a_detail = "ASMovieRoot 虚表指针为空";
				return false;
			}
			const auto slot = ReadPtr(vtable + kSlotAsRootInvoke * sizeof(std::uintptr_t));
			if (slot < ModuleBase() || slot >= ModuleBase() + ModuleSize()) {
				a_detail = std::format("ASMovieRoot 虚表[0x{:X}] 不是主模块里的代码（布局对不上）", kSlotAsRootInvoke);
				return false;
			}
			a_outRva = slot - ModuleBase();
			return true;
		}

		// ====================================================================
		// 三、菜单表查找（算法的照抄实现，见文件顶部注释）
		// ====================================================================

		// 一次查找的结果（诊断信息一起带出来，失败时日志里能看出「形状不对」还是「哈希没中」）。
		//
		// 这是个 POD —— 带 __try 的函数里不能有需要栈展开的成员（MSVC C2712）。
		struct FindOutcome
		{
			std::uintptr_t value{};      // 命中：指向「条目里的值」；0 = 没找到
			std::uint64_t  capacity{};   // 表容量（0 ⇒ 这个偏移根本不是菜单表）
			std::uint64_t  hashIndex{};  // 哈希算出的起始槽（诊断用）
			int            how{};        // 见 kFindHow*
		};

		constexpr int kFindShapeBad = 0;   // 形状不对（不是菜单表）
		constexpr int kFindHashMiss = 1;   // 形状对、哈希链走到空槽
		constexpr int kFindHashHit = 2;    // 哈希命中
		constexpr int kFindLinearHit = 3;  // 哈希没中、线性扫全表命中

		// 线性兜底最多扫多少个槽（真实菜单表只有几十~几百槽；这一层只是保险）
		constexpr std::uint64_t kMaxLinearSlots = 0x4000;

		// 在 a_map 里找 key = a_entryKey 的条目，返回**指向值的指针**（0 = 没找到）。
		//
		//   a_entryKey = BSFixedString 的 Entry*      → 比较用（string pool 唯一化 ⇒ 指针相等）
		//   a_charsPtr = 那个 Entry 的字符数据指针     → 哈希用（★ 别用 Entry* 算哈希）
		//
		// 先按引擎那条路走哈希；一旦没中就**线性扫全表兜底** —— 就算以后游戏改了哈希
		// 算法，这里也只是慢一点，不会像这轮一样直接查不到。
		FindOutcome ScatterFindValue(std::uintptr_t a_map, std::uintptr_t a_entryKey, std::uintptr_t a_charsPtr)
		{
			FindOutcome out;
			if (!a_map || !a_entryKey || !a_charsPtr) {
				return out;
			}
			__try {
				const auto* map = reinterpret_cast<const std::byte*>(a_map);
				const auto capacity = *reinterpret_cast<const std::uint64_t*>(map + kMapCapacityOffset);
				const auto* entries = *reinterpret_cast<const std::byte* const*>(map + kMapEntriesOffset);
				if (!entries || capacity < 2 || capacity > 0x20000 || (capacity & (capacity - 1)) != 0) {
					return out;  // 形状不对 ⇒ 这不是菜单表
				}
				out.capacity = capacity;

				const auto slotAt = [&](std::uint64_t a_index) {
					return entries + a_index * kEntryStride;
				};
				const auto slotKey = [&](std::uint64_t a_index) {
					return *reinterpret_cast<const std::uintptr_t*>(slotAt(a_index));
				};
				const auto slotNext = [&](std::uint64_t a_index) {
					return *reinterpret_cast<const std::int32_t*>(slotAt(a_index) + kEntryNextOffset);
				};

				// ① 哈希链（和引擎同一条路；哈希用的是**字符数据指针**）
				std::uint64_t index = (a_charsPtr ^ (a_charsPtr >> 32)) & (capacity - 1);
				out.hashIndex = index;
				for (std::uint32_t guard = 0; guard < 0x40; ++guard) {
					const auto next = slotNext(index);
					if (next == -1) {
						break;  // 空槽 ⇒ 哈希这条路没中
					}
					if (slotKey(index) == a_entryKey) {
						out.value = reinterpret_cast<std::uintptr_t>(slotAt(index) + kEntryValueOffset);
						out.how = kFindHashHit;
						return out;
					}
					index = static_cast<std::uint64_t>(static_cast<std::uint32_t>(next));
					if (index >= capacity) {
						break;
					}
				}

				// ② 线性兜底（哈希算法万一变了也不至于瞎）
				const auto slots = capacity < kMaxLinearSlots ? capacity : kMaxLinearSlots;
				for (std::uint64_t i = 0; i < slots; ++i) {
					if (slotNext(i) == -1) {
						continue;
					}
					if (slotKey(i) == a_entryKey) {
						out.value = reinterpret_cast<std::uintptr_t>(slotAt(i) + kEntryValueOffset);
						out.how = kFindLinearHit;
						return out;
					}
				}

				out.how = kFindHashMiss;
				return out;
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				return out;
			}
		}

		const char* FindHowName(int a_how)
		{
			switch (a_how) {
			case kFindHashMiss:
				return "哈希没中";
			case kFindHashHit:
				return "哈希命中";
			case kFindLinearHit:
				return "线性命中";
			default:
				return "形状不符";
			}
		}

		// ====================================================================
		// 四、解析缓存
		// ====================================================================

		struct Bridge
		{
			bool           ok{ false };
			std::uintptr_t menu{};      // IMenu*
			std::uintptr_t movie{};     // Scaleform::GFx::MovieImpl*
			std::uintptr_t asRoot{};    // Scaleform::GFx::AS3::MovieRoot*
			std::size_t    mapOffset{ kMenuMapOffset };
			std::size_t    menuInValueOffset{ kMenuPtrInValueOffset };
			std::size_t    uiMovieOffset{};     // Movie 取到自 IMenu 的哪个偏移
			std::size_t    asRootOffset{};      // ASMovieRoot 在 Movie 里的偏移（rootInInterface 时为 0）
			bool           rootInInterface{};   // true = menuObj._objectInterface 本身就是 MovieRoot
			char           menuName[64]{};
			char           menuRtti[192]{};
			char           movieRtti[192]{};
			char           rootRtti[192]{};
			char           where[80]{};         // 走了哪条路解析成功（日志用）
			std::string    detail;
		};

		Bridge& Cached()
		{
			static Bridge bridge;
			return bridge;
		}

		// 把某个对象里 0x??~0x?? 范围内「每个非空指针指向的对象的 RTTI 名字」列出来。
		// 只在**失败时**调用（一次菜单打开最多一次），用于让下一轮日志直接说明问题。
		std::string DescribeCandidates(std::uintptr_t a_obj, std::size_t a_first, std::size_t a_last, std::size_t a_step)
		{
			std::string s;
			for (std::size_t off = a_first; off <= a_last; off += a_step) {
				const auto candidate = ReadPtr(a_obj + off);
				if (!candidate) {
					continue;
				}
				char rtti[192]{};
				if (!SafeRttiName(reinterpret_cast<const void*>(candidate), rtti) || !rtti[0]) {
					std::snprintf(rtti, sizeof(rtti), "(无 RTTI)");
				}
				s += std::format(" 0x{:X}->{}", off, rtti);
			}
			return s.empty() ? std::string{ " (范围内没有任何非空指针)" } : s;
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

		// 值的 0x28 字节里，IMenu* 先按 IsMenuOpen 反汇编出来的 0x20 试，再按 8 字节步长扫全部 qword。
		constexpr std::size_t kMenuPtrCandidates[] = { 0x20, 0x00, 0x08, 0x10, 0x18 };

		bool ResolveMapAndMenu(RE::UI* a_ui, Bridge& a_out)
		{
			// ★ 两个指针，别搞混（见文件顶部）：
			//   entryKey = BSFixedString 里存的 Entry*（表里的 key 就是它，比较用）
			//   charsPtr = 那个 Entry 的字符数据（哈希用）
			static const RE::BSFixedString menuName{ kMenuName };
			const auto entryKey = *reinterpret_cast<const std::uintptr_t*>(std::addressof(menuName));
			const auto charsPtr = reinterpret_cast<std::uintptr_t>(menuName.c_str());
			if (!entryKey || !charsPtr) {
				a_out.detail = "BSFixedString(\"BSMissionMenu\") 未进入 string pool";
				return false;
			}

			const auto uiBase = reinterpret_cast<std::uintptr_t>(a_ui);

			std::string shapes;  // 诊断：形状通过的表偏移 + 查找结果
			std::string menus;   // 诊断：值里各 qword 指向对象的 RTTI（只有形状通过时才值得看）
			bool found = false;
			ForEachCandidate(0x3C0, 0x4C0, 8, [&](std::size_t mapOffset) {
				const auto outcome = ScatterFindValue(uiBase + mapOffset, entryKey, charsPtr);
				if (!outcome.capacity) {
					return false;  // 这个偏移上根本不是散列表
				}
				shapes += std::format(" 0x{:X}(cap=0x{:X} idx=0x{:X} {})",
					mapOffset, outcome.capacity, outcome.hashIndex,
					FindHowName(outcome.how));
				if (!outcome.value) {
					return false;
				}
				const auto value = outcome.value;
				// 判据 = 那个对象里存着自己的 menuName（同一个 string-pool Entry 指针）。
				bool hit = false;
				for (const auto inValueOffset : kMenuPtrCandidates) {
					const auto menu = ReadPtr(value + inValueOffset);
					if (!menu) {
						continue;
					}
					char rtti[192]{};
					if (!SafeRttiName(reinterpret_cast<const void*>(menu), rtti) || !rtti[0]) {
						std::snprintf(rtti, sizeof(rtti), "(无 RTTI)");
					}
					if (!ObjectContainsPointer(reinterpret_cast<const void*>(menu), entryKey, 0x200)) {
						menus += std::format(" 值+0x{:X}->{}(名字指针不匹配)", inValueOffset, rtti);
						continue;
					}
					a_out.mapOffset = mapOffset;
					a_out.menuInValueOffset = inValueOffset;
					a_out.menu = menu;
					std::memcpy(a_out.menuName, kMenuName, sizeof(kMenuName));
					std::memcpy(a_out.menuRtti, rtti, sizeof(a_out.menuRtti));
					menus += std::format(" 值+0x{:X}->{}✔", inValueOffset, rtti);
					hit = true;
					break;
				}
				if (hit) {
					found = true;
				}
				return hit;
			});

			if (!found) {
				a_out.detail = "UI 里没找到 BSMissionMenu 的菜单表条目｜候选表:" +
					(shapes.empty() ? std::string{ " 无(0x3C0~0x4C0 里没有形状像散列表的字段)" } : shapes) +
					"｜值内指针:" + (menus.empty() ? std::string{ " 无" } : menus);
				return false;
			}
			return true;
		}

		// ====================================================================
		// 五、身份判据与「IMenu → Movie → ASMovieRoot」解析
		//
		// 上一轮的失败根因（日志实证）：扫描用的是「RTTI 名字里含 Movie」这种模糊判据，
		// 于是在 IMenu+0x78 抓到了 menuObj 里的 **AS3 MovieClip 实例对象**
		// （`?AVMovieClip@fl_display@Instances@AS3@GFx@Scaleform@@` —— 名字里也有 "Movie"），
		// 从它身上当然找不到 ASMovieRoot。
		//
		// 这一轮改成三条硬判据：
		//   ① **虚表 RVA 精确比对**：MovieImpl / AS3::MovieRoot 的主虚表 RVA 离线量出来
		//      写死在常量里（全 exe 各只有一个类），一次指针比较就能定性，零误判；
		//   ② **多路径**：ObjectInterface::movieRoot → IMenu::uiMovie → IMenu 全对象扫描；
		//      拿到 Movie 后在它前 0x4000 字节里按①找 ASMovieRoot（含 ObjectInterface
		//      本身就是 MovieRoot 这一特例）；
		//   ③ 调用前再核对 Invoke 槽的 RVA（0x3368DC0），对不上就不调。
		// ====================================================================

		// 这个对象的虚表是不是「某个已知 RVA 的主虚表」
		bool VtableIs(std::uintptr_t a_obj, std::uintptr_t a_vtableRva)
		{
			return a_obj && ReadPtr(a_obj) == ModuleBase() + a_vtableRva;
		}

		bool RttiContains(std::uintptr_t a_obj, const char* a_needle)
		{
			if (!a_obj) {
				return false;
			}
			char rtti[192]{};
			if (!SafeRttiName(reinterpret_cast<const void*>(a_obj), rtti) || !rtti[0]) {
				return false;
			}
			return std::strstr(rtti, a_needle) != nullptr;
		}

		void RttiInto(char (&a_out)[192], std::uintptr_t a_obj)
		{
			if (!SafeRttiName(reinterpret_cast<const void*>(a_obj), a_out) || !a_out[0]) {
				std::snprintf(a_out, sizeof(a_out), "(无 RTTI)");
			}
		}

		bool LooksLikeMovie(std::uintptr_t a_obj)
		{
			return VtableIs(a_obj, kMovieImplVtableRva) || RttiContains(a_obj, "MovieImpl@GFx@Scaleform");
		}

		bool LooksLikeAsRoot(std::uintptr_t a_obj)
		{
			return VtableIs(a_obj, kMovieRootVtableRva) || RttiContains(a_obj, "MovieRoot@AS3@GFx@Scaleform");
		}

		// 在 a_obj 的前 a_bytes 字节里找「指向 AS3::MovieRoot 的指针」，
		// 返回**存它的那个槽的地址**（0 = 没找到）—— 返回地址是为了把偏移写进日志。
		std::uintptr_t FindAsRootSlot(std::uintptr_t a_obj, std::size_t a_bytes)
		{
			if (!a_obj || !IsMapped(reinterpret_cast<const void*>(a_obj), sizeof(std::uintptr_t))) {
				return 0;
			}
			const auto want = ModuleBase() + kMovieRootVtableRva;
			for (std::size_t off = 0; off + sizeof(std::uintptr_t) <= a_bytes; off += sizeof(std::uintptr_t)) {
				const auto slot = a_obj + off;
				const auto candidate = ReadPtr(slot);
				if (candidate && ReadPtr(candidate) == want) {
					return slot;
				}
			}
			return 0;
		}

		bool ResolveMovieChain(Bridge& a_out)
		{
			const auto menu = a_out.menu;
			const auto iface = ReadPtr(menu + kIMenuMenuObjOffset + kValueObjectInterfaceOffset);
			const auto as3Root = ReadPtr(menu + kIMenuMenuObjOffset + kValueDataOffset);
			const auto uiMovie = ReadPtr(menu + kIMenuUiMovieOffset);

			std::string diag = std::format(
				" IMenu+0x{:X}=0x{:X} IMenu+0x{:X}=0x{:X} IMenu+0x{:X}=0x{:X}",
				kIMenuMenuObjOffset + kValueObjectInterfaceOffset, iface,
				kIMenuMenuObjOffset + kValueDataOffset, as3Root,
				kIMenuUiMovieOffset, uiMovie);

			// ⚡ 特例：AS3 的 Value::ObjectInterface 有可能就是 MovieRoot 本体
			if (LooksLikeAsRoot(iface)) {
				a_out.asRoot = iface;
				a_out.rootInInterface = true;
				a_out.asRootOffset = 0;
				RttiInto(a_out.rootRtti, iface);
				std::snprintf(a_out.where, sizeof(a_out.where), "menuObj._objectInterface 本体");
			}

			// ① 收集 Movie 候选（顺序 = 可信度）
			constexpr std::size_t kMaxCand = 8;
			std::uintptr_t cand[kMaxCand]{};
			std::size_t    candMenuOff[kMaxCand]{};
			const char*    candHow[kMaxCand]{};
			std::size_t    count = 0;
			const auto addCand = [&](std::uintptr_t a_obj, std::size_t a_menuOff, const char* a_how) {
				if (!a_obj || count >= kMaxCand) {
					return;
				}
				for (std::size_t i = 0; i < count; ++i) {
					if (cand[i] == a_obj) {
						return;
					}
				}
				cand[count] = a_obj;
				candMenuOff[count] = a_menuOff;
				candHow[count] = a_how;
				++count;
			};

			addCand(ReadPtr(iface + kObjectInterfaceMovieRootOffset),
				kIMenuMenuObjOffset + kValueObjectInterfaceOffset, "ObjectInterface(+0x8)");
			addCand(uiMovie, kIMenuUiMovieOffset, "IMenu::uiMovie");
			for (std::size_t off = 0; off <= 0x200; off += 8) {
				const auto p = ReadPtr(menu + off);
				if (p && LooksLikeMovie(p)) {
					addCand(p, off, "IMenu 内扫描");
				}
			}

			// ② 逐个候选：定性 + 在里面找 ASMovieRoot
			std::string seen;
			for (std::size_t i = 0; i < count; ++i) {
				char rtti[192]{};
				RttiInto(rtti, cand[i]);
				const bool isMovie = LooksLikeMovie(cand[i]);
				seen += std::format(" [{}]=IMenu+0x{:X}({}){}", candHow[i], candMenuOff[i], rtti, isMovie ? "✔" : "✘");
				if (!isMovie) {
					continue;
				}
				if (!a_out.movie) {
					a_out.movie = cand[i];
					a_out.uiMovieOffset = candMenuOff[i];
					std::memcpy(a_out.movieRtti, rtti, sizeof(a_out.movieRtti));
				}
				if (!a_out.asRoot) {
					const auto slot = FindAsRootSlot(cand[i], kMovieScanBytes);
					if (slot) {
						a_out.asRoot = ReadPtr(slot);
						a_out.asRootOffset = slot - cand[i];
						RttiInto(a_out.rootRtti, a_out.asRoot);
						std::snprintf(a_out.where, sizeof(a_out.where), "%s → MovieImpl+0x%zX",
							candHow[i], a_out.asRootOffset);
					}
				}
			}

			// ③ 兜底：AS3 根对象 / ObjectInterface 自身里也扫一遍
			if (!a_out.asRoot && as3Root) {
				const auto slot = FindAsRootSlot(as3Root, kObjectScanBytes);
				if (slot) {
					a_out.asRoot = ReadPtr(slot);
					a_out.asRootOffset = slot - as3Root;
					RttiInto(a_out.rootRtti, a_out.asRoot);
					std::snprintf(a_out.where, sizeof(a_out.where), "AS3 根对象(IMenu+0x%X)+0x%zX",
						static_cast<unsigned>(kIMenuMenuObjOffset + kValueDataOffset), a_out.asRootOffset);
				}
			}
			if (!a_out.asRoot && iface) {
				const auto slot = FindAsRootSlot(iface, kObjectScanBytes);
				if (slot) {
					a_out.asRoot = ReadPtr(slot);
					a_out.asRootOffset = slot - iface;
					RttiInto(a_out.rootRtti, a_out.asRoot);
					std::snprintf(a_out.where, sizeof(a_out.where), "ObjectInterface+0x%zX", a_out.asRootOffset);
				}
			}

			if (!a_out.asRoot) {
				a_out.detail = std::format("IMenu(0x{:X}) 里没解析出 ASMovieRoot｜候选指针:{}｜Movie 候选:{}",
					menu, diag, seen.empty() ? std::string{ " 无" } : seen);
				return false;
			}
			a_out.detail = std::format("途径={}｜候选指针:{}｜Movie 候选:{}", a_out.where, diag,
				seen.empty() ? std::string{ " 无" } : seen);
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

		// SetVariable 通路用（载荷先放 root 变量，再无参 Invoke；见 kAttempts 注释）。
		bool SafeSetVariable(RE::Scaleform::GFx::ASMovieRootBase* a_root, const char* a_path,
			const RE::Scaleform::GFx::Value& a_value)
		{
			__try {
				return a_root->SetVariable(a_path, a_value);
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				return false;
			}
		}

		// ================================================================
		// ★★ 第 8 轮修正：读 GFx 返回的**数值**必须按类型读，不能一律 GetNumber()。
		//
		//   踩坑实录：AS3 侧 `SetAvailableQuests():int` 返回 202，我们却记成
		//   「返回 0」——因为 GFx 的 Value 是联合体：
		//     kInt   → 值存在 _value.int32（低 4 字节）
		//     kNumber→ 值存在 _value.number（整个 8 字节的 double）
		//   GetNumber() 直接返回 `_value.number`，于是把 int 的位模式**当成 double**：
		//     202（0x00000000000000CA）→ 1e-321 ⇒ 格式化出来是 "0"
		//     -1 （0x00000000FFFFFFFF）→ 2.12e-314 ⇒ 打印 "0" 但**仍然 > 0**
		//   后果不只是日志难看：`reported > 0` 这个成功判据被整数位模式**意外满足**，
		//   连 AS3 明确报的失败码（-1 载荷没到 / -2 解析失败）都会被当成成功。
		//   （第 8 轮日志实证：推送成功、胜出的那条 `_root.SAQ_SetAvailableQuests=ok(返回 0)`
		//     其实是"返回了一个正数" —— 因为循环正是在这一条 break 的。）
		// ================================================================
		bool SafeReadValueNumber(const RE::Scaleform::GFx::Value& a_value, double& a_out)
		{
			__try {
				if (a_value.IsInt()) {
					a_out = static_cast<double>(a_value.GetInt());
					return true;
				}
				if (a_value.IsUInt()) {
					a_out = static_cast<double>(a_value.GetUInt());
					return true;
				}
				if (a_value.IsNumber()) {
					a_out = a_value.GetNumber();
					return true;
				}
				if (a_value.IsBoolean()) {
					a_out = a_value.GetBoolean() ? 1.0 : 0.0;
					return true;
				}
			} __except (EXCEPTION_EXECUTE_HANDLER) {
			}
			return false;
		}

		// 日志转义：探针/回报读回来的字符串里带 \n \t（载荷本身就是多行的），
		// 原样写进日志会把一行日志劈成好几行（第 7 轮日志就是三行拼一行），
		// 这里统一转成可见的 \n \r \t。
		std::string EscapeForLog(std::string_view a_text, std::size_t a_maxLen = 0)
		{
			std::string out;
			out.reserve(a_text.size() + 8);
			for (const char ch : a_text) {
				if (a_maxLen && out.size() >= a_maxLen) {
					out += "…";
					break;
				}
				switch (ch) {
				case '\n': out += "\\n"; break;
				case '\r': out += "\\r"; break;
				case '\t': out += "\\t"; break;
				default: out += ch; break;
				}
			}
			return out;
		}

		// 读 GFx 返回值里的字符串（POD 输出，避免 C2712）。
		bool SafeReadValueString(const RE::Scaleform::GFx::Value& a_value, char* a_out, std::size_t a_outSize)
		{
			a_out[0] = '\0';
			__try {
				if (a_value.IsString()) {
					const char* s = a_value.GetString();
					if (s) {
						std::size_t i = 0;
						for (; i + 1 < a_outSize && s[i] != '\0'; ++i) {
							a_out[i] = s[i];
						}
						a_out[i] = '\0';
						return true;
					}
				}
			} __except (EXCEPTION_EXECUTE_HANDLER) {
			}
			return false;
		}

		std::string Describe(const Bridge& a_bridge)
		{
			std::string s;
			s += "菜单表=UI+0x";
			s += std::format("{:X}", a_bridge.mapOffset);
			s += " IMenu=值+0x";
			s += std::format("{:X}", a_bridge.menuInValueOffset);
			s += "(" + std::string(a_bridge.menuRtti) + ")";
			s += " Movie=IMenu+0x";
			s += std::format("{:X}", a_bridge.uiMovieOffset);
			s += "(" + std::string(a_bridge.movieRtti) + ")";
			s += a_bridge.rootInInterface ? " ASMovieRoot=menuObj._objectInterface" : " ASMovieRoot=Movie+0x";
			if (!a_bridge.rootInInterface) {
				s += std::format("{:X}", a_bridge.asRootOffset);
			}
			s += "(" + std::string(a_bridge.rootRtti) + ") @" + a_bridge.where;
			return s;
		}
	}

	// ★ 每次菜单「由关变开」都要清一次缓存：菜单一关，SWF 的 Movie 对象通常就被
	//   销毁了（Ptr<Movie> 释放），下一帧再拿旧指针去 Invoke 是野指针。
	//   （实测第 3 轮的失败日志里，同一个 session 内缓存跨菜单复用是隐患。）
	void Reset()
	{
		Cached() = Bridge{};
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
		if (!ResolveMovieChain(bridge)) {
			a_detail = "Movie/ASMovieRoot 解析失败：" + bridge.detail +
				"｜IMenu 内各指针的 RTTI:" + DescribeCandidates(bridge.menu, 0x58, 0x180, 8);
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
		// 把任务列表编成一行行文本（AS3 侧 MissionMenu.SaqParsePayload 解析，
		// 协议与 SWF 内嵌的回退数据完全一致）：
		//     SAQ1
		//     T\t可接任务\tAvailable
		//     Q\t<FormID>\t<type>\t<中文名>\t<英文名>
		//
		// ★ 标题和名字都带**中英两份**，由 AS3 侧按游戏语言挑：C++ 侧拿不到可靠的语言
		//   （实测本机 INI 里根本没有 sLanguage，游戏是中文但读到的是空/英文），
		//   而 AS3 侧能直接看引擎推来的任务名 —— 那是本地化的，判定最准。
		// 名字里可能有任意标点，所以用 Tab 分隔、名字放最后。
		std::string BuildPayloadUtf8(const std::vector<QuestEntry>& a_quests)
		{
			std::string s;
			s.reserve(a_quests.size() * 48 + 96);
			s += "SAQ1\n";
			s += "T\t" + std::string{ kTabTitleZh } + "\t" + std::string{ kTabTitleEn } + "\n";
			for (const auto& q : a_quests) {
				std::string zh = q.nameZh;
				std::string en = q.nameEn;
				for (auto* name : { &zh, &en }) {
					for (auto& ch : *name) {
						if (ch == '\r' || ch == '\n' || ch == '\t') {
							ch = ' ';
						}
					}
				}
				s += "Q\t";
				s += std::to_string(q.formID);
				s += "\t";
				s += std::to_string(q.type);
				s += "\t";
				s += zh;
				s += "\t";
				s += en;
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

		// 一次尝试 = 一种「载荷通路」× 一种「参数编码」× 一种「函数路径」。
		//
		// 通路有两种（kind 1 是第 7 轮新增）：
		//   kind 0：Invoke(path, 载荷)                        —— 载荷当参数传；
		//   kind 1：SetVariable("SAQ_Payload", 载荷) + Invoke(path)（无参）—— 载荷放 root 变量。
		//
		// 为什么加 kind 1：第 6 轮实测「调用 ok、返回值却是 0」，而返回值 0 在 AS3 侧
		// 只有一种解释（参数非空但解析不出条目）。Invoke 的**传参链路**是唯一可疑环节，
		// SetVariable 是另一条完全不同的代码路径，既能当对照组、也能当兜底。
		struct Attempt
		{
			int         kind;  // 0 = Invoke(带参)；1 = SetVariable + Invoke(无参)
			bool        wide;  // true = 宽字符 Value（UTF-16）；false = CreateString(UTF-8)
			const char* path;
		};
		constexpr Attempt kAttempts[] = {
			// ★ 实测（第 8 轮日志）：**只有带 `_root.` 前缀的路径能命中**，
			//   裸名字三条全 fail —— 所以把能命中的放最前，别每次白试。
			//   （SWF 侧挂在 root 上；见 MissionMenu.SaqPublishEntryPoint。）
			{ 0, true, "_root.SAQ_SetAvailableQuests" },
			// 对照组（都留在表里：一旦哪天 SWF 侧改了挂法，这里能立刻看出来）
			{ 0, true, "SAQ_SetAvailableQuests" },
			{ 1, true, "_root.SAQ_ApplyPayload" },
			{ 1, true, "SAQ_ApplyPayload" },
			{ 0, true, "_root.SetAvailableQuests" },
			{ 0, true, "SetAvailableQuests" },
			{ 0, true, "_root.root.SetAvailableQuests" },
			{ 0, false, "_root.SAQ_SetAvailableQuests" },
			{ 0, false, "SAQ_SetAvailableQuests" },
			{ 1, false, "_root.SAQ_ApplyPayload" },
			{ 1, false, "SAQ_ApplyPayload" },
			{ 0, false, "_root.SetAvailableQuests" },
			{ 0, false, "SetAvailableQuests" },
			{ 0, false, "_root.root.SetAvailableQuests" },
		};
	}

	// 返回值的类型名（日志用）：AS3 那边没这个方法时通常得到 undefined。
	const char* DescribeValueType(const RE::Scaleform::GFx::Value& a_value)
	{
		if (a_value.IsUndefined()) {
			return "undefined";
		}
		if (a_value.IsNumber() || a_value.IsInt() || a_value.IsUInt()) {
			return "数值";
		}
		if (a_value.IsString() || a_value.IsStringW()) {
			return "字符串";
		}
		if (a_value.IsBoolean()) {
			return "布尔";
		}
		if (a_value.IsObject()) {
			return "对象";
		}
		if (a_value.IsArray()) {
			return "数组";
		}
		return "其它";
	}

	// 诊断：调 AS3 的 SAQ_Probe，让它把「收到的字符串长度+前缀」原样回读回来。
	// 这条日志把三种情况一次分清楚：
	//   正常（`<长度>|SAQ1 Q ...`）→ 参数传输没问题，问题在解析/逻辑；
	//   `null` / 长度 0          → 参数根本没送到；
	//   别的形状                 → 编码/截断问题。
	// （SWF 还是旧版时会 `=fail`，恰好也能告出「SWF 没更新」。）
	std::string ProbeAs3String(RE::Scaleform::GFx::ASMovieRootBase* a_root, const char* a_path,
		const std::wstring& a_wide, const std::string& a_utf8, bool a_useWide)
	{
		RE::Scaleform::GFx::Value arg;
		bool argReady = false;
		if (a_useWide) {
			arg = RE::Scaleform::GFx::Value(a_wide.c_str());
			argReady = true;
		} else if (VtableSlotInModule(a_root, kSlotAsRootCreateString)) {
			argReady = SafeCreateString(a_root, &arg, a_utf8.c_str());
		}
		if (!argReady) {
			return std::string{ a_path } + "=arg失败";
		}
		RE::Scaleform::GFx::Value ret;
		if (!SafeInvoke(a_root, a_path, &ret, &arg, 1)) {
			return std::string{ a_path } + "=fail";
		}
		char buf[160]{};
		if (SafeReadValueString(ret, buf, sizeof(buf))) {
			std::string s{ a_path };
			s += "=";
			s += buf;
			return s;
		}
		std::string s{ a_path };
		s += "=(非字符串:";
		s += DescribeValueType(ret);
		s += ")";
		return s;
	}

	// 无参调用，并把返回值（字符串/数值）读回来 —— 诊断用（SAQ_Report / SAQ_Probe）。
	std::string CallAs3NoArg(RE::Scaleform::GFx::ASMovieRootBase* a_root, const char* a_path)
	{
		RE::Scaleform::GFx::Value ret;
		if (!SafeInvoke(a_root, a_path, &ret, nullptr, 0)) {
			return std::string{ a_path } + "=fail(路径不存在或调用失败)";
		}
		char buf[512]{};
		if (SafeReadValueString(ret, buf, sizeof(buf))) {
			return std::string{ a_path } + "=" + buf;
		}
		double num{};
		if (SafeReadValueNumber(ret, num)) {
			return std::format("{}=数值 {}", a_path, num);
		}
		return std::format("{}=(非字符串/数值: {})", a_path, DescribeValueType(ret));
	}

	bool PushAvailableQuests(const std::vector<QuestEntry>& a_quests, std::string& a_detail)
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
		std::uintptr_t invokeRva{};
		if (std::string slotDetail; !CheckInvokeSlot(bridge.asRoot, invokeRva, slotDetail)) {
			a_detail = slotDetail;
			return false;
		}
		if (invokeRva != kInvokeRva) {
			// 虚表槽内容与离线验证值不符 ⇒ 说明"这个对象其实不是本版本的 AS3::MovieRoot"。
			// 宁可这次不推（SWF 里自带内嵌回退数据，界面不会空），也不能乱调别人的虚函数。
			a_detail = std::format("ASMovieRoot 虚表[0x{:X}] 指向 0x{:X}，与离线验证值 0x{:X} 不符 ⇒ 拒绝调用",
				kSlotAsRootInvoke, invokeRva, kInvokeRva);
			Reset();
			return false;
		}
		const auto slotNote = std::format(" Invoke槽=ASMovieRoot+0x{:X}", invokeRva);

		const std::string payloadUtf8 = BuildPayloadUtf8(a_quests);
		const std::wstring payloadWide = Utf8ToWide(payloadUtf8);
		if (payloadWide.empty()) {
			a_detail = "载荷编码失败（UTF-8 -> UTF-16）";
			return false;
		}

		// ★ 诊断（第 7 轮）：先问 AS3「你收到的字符串长什么样」（见 ProbeAs3String）。
		//   第 8 轮实测结论：`_root.SAQ_Probe=6743|SAQ1\nT\t可接任务\tAvailable\nQ\t`
		//   —— 载荷**完整**送到（6743 字符 = 8561 字节 UTF-8 的中文一字一 char），
		//   且 24 字符前缀与载荷开头逐字相符 ⇒ 参数链路没有问题。
		//   （裸名字那条 `SAQ_Probe=fail`，与 kAttempts 的实测一致：必须带 `_root.` 前缀。）
		const std::string probeS = ProbeAs3String(root, "_root.SAQ_Probe", payloadWide, payloadUtf8, false);
		const std::string probeW = ProbeAs3String(root, "SAQ_Probe", payloadWide, payloadUtf8, true);

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
			bool called = false;
			if (attempt.kind == 1) {
				// SetVariable 通路：先把载荷放进 root 的 SAQ_Payload，再**无参** Invoke。
				if (VtableSlotInModule(root, kSlotAsRootSetVariable) && SafeSetVariable(root, "SAQ_Payload", args[0])) {
					called = SafeInvoke(root, attempt.path, &ret, nullptr, 0);
				}
			} else {
				called = SafeInvoke(root, attempt.path, &ret, args, 1);
			}

			// ★ 按类型读（见 SafeReadValueNumber 的注释：一律 GetNumber() 会把 int 读成 1e-321）。
			double reported = 0.0;
			bool hasNumber = false;
			if (called) {
				hasNumber = SafeReadValueNumber(ret, reported);
			}

			trail += std::string{ trail.empty() ? "" : " | " } + (attempt.kind == 1 ? "V" : "") + (attempt.wide ? "W:" : "S:") + attempt.path;
			trail += called ? "=ok" : "=fail";
			if (hasNumber) {
				trail += std::format("(返回 {:.0f}", reported);
				if (reported < 0.0) {
					// AS3 侧的约定（MissionMenu.SetAvailableQuests）：-1 = 参数空/null；
					// -2 = 参数非空但解析不出条目（此时 AS3 已自动回退内嵌表）。
					trail += reported == -1.0 ? "：载荷没送到" : (reported == -2.0 ? "：解析失败(已回退内嵌表)" : "：未知错误码");
				}
				trail += ")";
			} else if (called) {
				trail += std::format("(返回 {})", DescribeValueType(ret));
			}

			// AS3 侧返回「解析到的条数」：>0 才算成功。
			if (called && reported > 0.0) {
				ok = true;
				break;
			}
		}

		// ★ 状态回读（第 8 轮新增）：把界面此刻的真实状态读回来。
		// 第 7 轮的教训是「日志说成功、却没人能证明界面显示了什么」，只能靠肉眼进游戏核对；
		// SAQ_Report 一次给出「解析几条/过滤后几条/列表几条/掩码/选中 tab/语言/标题」，
		// 从此这一层在日志里就能闭环（SWF 还是旧版时会显示 fail，也能一眼看出）。
		const std::string report = EscapeForLog(CallAs3NoArg(root, "_root.SAQ_Report"), 400);

		// 先把解析信息留一份 —— 失败时下面会 Reset()，缓存里的 detail 会被清掉。
		const std::string bridgeDetail = bridge.detail;

		if (!ok) {
			// 全部组合失败：把缓存清掉，下一次重试（或下次开菜单）从「找菜单表」重新来一遍
			// —— 菜单刚开那一两帧 Movie 可能还在换代的中间态，缓存住就没救了。
			Reset();
		}

		a_detail = bridgeDetail + slotNote +
			" 探针: " + EscapeForLog(probeS, 120) + " | " + EscapeForLog(probeW, 120) +
			" 调用: " + trail +
			std::format(" 载荷={} 字节/{} 条", payloadUtf8.size(), a_quests.size()) +
			" 状态: " + report;
		return ok;
	}

	// ★ 第 9 轮：只读地把界面自报状态取回来（供菜单开着时的「变化即记」轮询用）。
	//
	// 与 PushAvailableQuests 里的那次回读是同一入口（`_root.SAQ_Report`），
	// 区别只是这里**不推送**、也不写自己的日志：桥没通 / SWF 是旧版时返回 false，
	// 由调用方决定要不要记（这样不会因为轮询把日志刷满）。
	bool ReadUiReport(std::string& a_report)
	{
		std::string detail;
		if (!EnsureResolved(detail)) {
			return false;
		}
		auto& bridge = Cached();
		auto* root = reinterpret_cast<RE::Scaleform::GFx::ASMovieRootBase*>(bridge.asRoot);
		if (!root) {
			return false;
		}
		const std::string raw = CallAs3NoArg(root, "_root.SAQ_Report");
		if (raw.find("=fail") != std::string::npos) {
			return false;  // 路径不存在 / 调用失败（SWF 旧版或桥在换代的中间态）
		}
		a_report = EscapeForLog(raw, 400);
		return true;
	}

	// ★ 第 10 轮：读 AS3 侧一个**无参函数的字符串返回值**（不带 CallAs3NoArg 的
	//   "路径=" 前缀、不做日志转义）—— 引导请求就是靠它回传的：
	//     AS3 侧 SaqGuideSeq/SaqGuideQuest 变化 → SAQ_PeekGuide() 返回 "<seq>|<questFormID>"
	//   为什么不读变量：GetVariable 的虚表槽序号（commonlibsf 标 0x32）在本版本没验证过，
	//   而 Invoke 槽是我们**已经比对过 RVA**（0x3368DC0）的那条路，宁可用验过的路。
	//   返回 false = 桥没通 / SWF 旧版 / 返回值不是字符串（调用方静默跳过）。
	bool ReadUiString(const char* a_path, std::string& a_value)
	{
		std::string detail;
		if (!EnsureResolved(detail)) {
			return false;
		}
		auto& bridge = Cached();
		auto* root = reinterpret_cast<RE::Scaleform::GFx::ASMovieRootBase*>(bridge.asRoot);
		if (!root) {
			return false;
		}
		RE::Scaleform::GFx::Value ret;
		if (!SafeInvoke(root, a_path, &ret, nullptr, 0)) {
			return false;
		}
		char buf[256]{};
		if (!SafeReadValueString(ret, buf, sizeof(buf))) {
			return false;
		}
		a_value = buf;
		return true;
	}
}
