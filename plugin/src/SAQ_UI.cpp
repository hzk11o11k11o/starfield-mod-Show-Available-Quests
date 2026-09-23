#include "PCH.h"

#include "SAQ_UI.h"

// ★ 第 36 轮：载荷 `P` 行要用「代理任务的运行期 FormID」，加载前缀只有引导通道知道
//   （SAQ_Guide.cpp 的 GLOB 认领）——所以这里读它。EnsureChannel 有缓存，开销只是一次读。
#include "SAQ_Guide.h"

// ★★ 第 84 轮：`Decision::Utf8SafeCut` —— 日志/结果里的截断必须按字符边界
//   （旧实现按字节切，实测把「追踪者联盟」切成 `追踪` + 半个 `者` ⇒ 结果 JSON 非法）。
#include "SAQ_Decision.h"

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

		// ★ 第 12 轮：不再先做 IsMapped（VirtualQuery）——实测「推送失败（重试）… 耗时 3921 ms」
		//   的失败路径里，`FindAsRootSlot` 一次要跑 2048 步 ×2 次 ReadPtr，而每一步 ReadPtr
		//   都会先 VirtualQuery（内核调用）。VirtualQuery 正常只要 ~μs 级，但在游戏进程里
		//   （VAD 树大、与引擎的内存操作抢锁）实测明显更贵，4096+ 次累计成秒级卡顿。
		//   改成**纯 __try**：有效指针零额外开销；坏指针走一次结构化异常（~几十 μs，
		//   且只发生在坏指针上）。语义与之前完全等价（读不到就返回兜底值）。
		//
		//   （IsMapped 函数本身保留：将来若要做「大范围预检」还有用。）
		template <class T>
		T SafeRead(const void* a_src, T a_fallback)
		{
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
					const char raw = name[i];
					if (raw == '\0') {
						return true;
					}
					// ★★ 第 84 轮：只保留可打印 ASCII —— MSVC 修饰名本来就只有这些字符。
					//   旧实现直接抄字节：指针误判（候选偏移刚好指着随机数据）时，读到的
					//   乱码进了日志 —— 实测日志里出现 `0x160->H…`（非法 UTF-8，结果 JSON
					//   因此整体不可解析）和控制字符（把一行诊断劈成好几行）。
					//   非可打印字节换成 `.`（保留「这里有个字节」的信息量，且人眼可读）。
					const auto b = static_cast<unsigned char>(raw);
					a_out[i] = (b >= 0x20u && b < 0x7Fu) ? raw : '.';
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

		// 线性兜底最多扫多少个槽（真实菜单表只有几十~几百槽；这一层只是保险）。
		// ★ 第 11 轮：0x4000 → 0x1000。排查「打开菜单卡顿」时审过这段：形状检查只看
		//   capacity/entries 两个字段，**误判成本 = 全表扫一遍**（每槽 stride 0x38，
		//   0x4000 槽要碰 917KB 内存）；0x1000 仍远大于真实表规模（0x200），兜底能力不减。
		constexpr std::uint64_t kMaxLinearSlots = 0x1000;

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

			// 试一个候选偏移：形状对了 + 值里拿到「名字指针对得上」的 IMenu 才算命中。
			const auto tryOffset = [&](std::size_t mapOffset) -> bool {
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
				return hit;
			};

			// ★ 第 11 轮：**实测值先试**（UI+0x450 = IsMenuOpen 反汇编 + 多轮实测的正确偏移），
			//   不命中才扫邻域 0x3C0~0x4C0 兜底 —— 原来顺序扫描时 0x450 排在第 19 个，
			//   前面 18 个偏移每次都要白跑「形状检查 + 可能的兜底线性扫描」。
			bool found = tryOffset(kMenuMapOffset);
			if (!found) {
				ForEachCandidate(0x3C0, 0x4C0, 8, [&](std::size_t mapOffset) {
					if (mapOffset == kMenuMapOffset) {
						return false;  // 已经试过
					}
					const bool hit = tryOffset(mapOffset);
					if (hit) {
						found = true;
					}
					return hit;
				});
			}

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
			// ★ 第 12 轮：开头的 IsMapped 预检去掉（ReadPtr 自己已有 __try 保护；
			//   这里是「扫 16KB」的热点，预检省下的每一次内核调用都是净赚）。
			if (!a_obj) {
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
		//
		// ★★ 第 84 轮修（自动测试二跑实证）：截断原来**按输出字节**数
		//   （`out.size() >= a_maxLen`），会把多字节汉字切成半个 —— 实测结果 JSON 里
		//   出现 `追踪` + `者` 的首字节 `0xE8` + `…`（非法 UTF-8）⇒ `check_results.py`
		//   解码结果文件时当场抛错、22 条用例的结果一条也读不出来（判据通道失效）。
		//   现在：① 截断走 `Decision::Utf8SafeCut`（切点回退到字符首字节 —— 绝不会
		//   切出坏字节）；② 上限按**输入**字节数算（转义膨胀不再撞上限）。
		std::string EscapeForLog(std::string_view a_text, std::size_t a_maxLen = 0)
		{
			const std::size_t take = Decision::Utf8SafeCut(a_text, a_maxLen);
			const bool clipped = take < a_text.size();
			std::string out;
			out.reserve(take + 8);
			for (std::size_t i = 0; i < take; ++i) {
				switch (a_text[i]) {
				case '\n': out += "\\n"; break;
				case '\r': out += "\\r"; break;
				case '\t': out += "\\t"; break;
				default: out += a_text[i]; break;
				}
			}
			if (clipped) {
				out += "…";
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

		// ★ 第 12 轮：分解耗时（表解析 / Movie 链解析 / 失败诊断）——
		//   上一轮实测「推送失败（重试）… 耗时 3921 ms」，但从日志里看不出钱花在哪一段。
		//   计时写进 detail：失败与成功两边都会出现在日志里。
		const auto t0 = ::GetTickCount64();
		if (!ResolveMapAndMenu(ui, bridge)) {
			a_detail = (bridge.detail.empty() ? std::string{ "菜单表解析失败" } : bridge.detail) +
				std::format("（表 {} ms）", ::GetTickCount64() - t0);
			bridge.detail.clear();
			return false;
		}
		const auto t1 = ::GetTickCount64();
		if (!ResolveMovieChain(bridge)) {
			const auto t2 = ::GetTickCount64();
			a_detail = "Movie/ASMovieRoot 解析失败：" + bridge.detail +
				"｜IMenu 内各指针的 RTTI:" + DescribeCandidates(bridge.menu, 0x58, 0x180, 8) +
				std::format("（表 {} ms / 链 {} ms / 诊断 {} ms）",
					t1 - t0, t2 - t1, ::GetTickCount64() - t2);
			bridge.detail.clear();
			return false;
		}

		bridge.ok = true;
		bridge.detail = Describe(bridge) +
			std::format("（表 {} ms / 链 {} ms）", t1 - t0, ::GetTickCount64() - t1);
		a_detail = bridge.detail;
		return true;
	}

	// ★★★ 第 133 轮（P3 产品化 PoC · docs/15 11.7）：见头文件里的说明。
	//   注入层（SAQ_UiInject）与 SWF 通道共用同一条解析链。
	std::uintptr_t ResolvedAsMovieRoot()
	{
		return Cached().asRoot;
	}

	namespace
	{
		// ★ 第 36 轮：代理任务（SAQ_MainQuest，记录号 0x800）的运行期 FormID。
		//   为什么要推给界面：原版任务菜单按 R（SET COURSE）时，引擎取「目标位置」→
		//   打开星图 → 聚焦目标星球 → 询问是否导航。我们的可接任务在引擎侧不存在，
		//   但**代理任务**是真实任务、它的目标别名此刻绑着「接取地点」引用（脚本
		//   ForceRefTo）—— 第 36 轮因此把它交给原版的 MissionMenu_PlotToLocation 流程。
		//
		//   ★★ 第 44 轮实测更正：那条 dispatch **确实生效**，但用的是代理任务**上一次**
		//   的目标位置（此刻脚本还没 ForceRefTo）⇒ 星图位置永远滞后一条；而且它一打开
		//   星图游戏就暂停，脚本的补救调用再也跑不到。所以 AS3 侧已删掉 dispatch，
		//   星图改由 Papyrus 用本次引导目标的地点打开（见 SAQ_Main.psc 的
		//   ProcessStarMapPending）。这个 FormID 现在只用于报告里的 `proxy=0x…` 诊断。
		//
		//   FormID = (插件加载前缀 << 24) | 0x800（记录号，见 SAQ.cpp::kOwnQuestLocal）。
		//   前缀是**运行期**才知道的（ESM 通道认领时得到）；没认领（ESM 没启用 /
		//   脚本没跑）就返回 0 —— 界面据此跳过原版流程，只保留我们自己的引导。
		std::uint32_t ProxyQuestFormID()
		{
			constexpr std::uint32_t kProxyQuestLocal = 0x800;
			const auto ch = SAQ::Guide::EnsureChannel();
			if (!ch.resolved) {
				return 0;
			}
			return (ch.prefix << 24) | kProxyQuestLocal;
		}

		// 把任务列表编成一行行文本（AS3 侧 MissionMenu.SaqParsePayload 解析，
		// 协议与 SWF 内嵌的回退数据完全一致）：
		//     SAQ1
		//     T\t可接任务\tAvailable
		//     P\t<代理任务FormID>（第 36 轮；0 = 通道没认领，界面跳过原版星图流程）
		//     Q\t<FormID>\t<type>\t<中文名>\t<英文名>\t<有无引导目标>\t<是否全是非常驻候选>\t<阵营>\t<同伴固定显示>\t<说明中>\t<说明英>\t<可重复任务>
		//   （第 23 轮追加「有无引导目标」；★ 第 46 轮追加「是否全是非常驻候选」——
		//    "1" = 该任务的全部候选都非常驻（远处一定取不到，需要靠近目标区域）。
		//     界面据此在描述里**提前**说明「需要靠近」，见 MissionMenu.SaqDescriptionText。
		//    旧版 AS3 / 内嵌回退数据缺列时按 "0"（不需要靠近）处理，向后兼容）
		//   ★ 第 65 轮（任务专属图标）追加「阵营」：原版 UI 的阵营枚举（-1 = 无阵营），
		//     离线由 QUST 的 FTYP 关键字映射（tools/esm/gen_faction_types.py）。
		//     界面原样交给原版 MissionsListEntry.SetFactionIcon(iFaction, iType)，
		//     图标与原版任务菜单一致；缺列（旧 SWF / 旧数据）按 -1 处理。
		//   ★★ 协议纪律：**新列只能追加在最后** —— AS3 解析按列号取值、按 length 判缺列，
		//     往中间插列会让新 SWF 读旧载荷时把「阵营」当成别的字段（第 65 轮踩过：
		//     内嵌回退载荷缺「需要靠近」列 ⇒ 阵营列被误读成它）。
		//   ★★ 第 89 轮（可重复任务）追加**第 11 列** = 可重复标记（"1"/"0"）——
		//     AS3 侧 FilterKnownQuests 据此豁免「在玩家日志里」的丢弃（已完成 + 可重复
		//     ⇒ 保留；进行中照旧隐藏）。缺列（旧 SWF / 旧数据）⇒ 按 "0" 处理。
		//
		// ★ 标题和名字都带**中英两份**，由 AS3 侧按游戏语言挑：C++ 侧拿不到可靠的语言
		//   （实测本机 INI 里根本没有 sLanguage，游戏是中文但读到的是空/英文），
		//   而 AS3 侧能直接看引擎推来的任务名 —— 那是本地化的，判定最准。
		// 名字里可能有任意标点，所以用 Tab 分隔、名字放最后。
		std::string BuildPayloadUtf8(const std::vector<QuestEntry>& a_quests)
		{
			std::string s;
			s.reserve(a_quests.size() * 48 + 128);
			s += "SAQ1\n";
			s += "T\t" + std::string{ kTabTitleZh } + "\t" + std::string{ kTabTitleEn } + "\n";
			// ★ 第 36 轮：P = 代理任务 FormID（SET COURSE 时把原版星图流程跑起来，见上面的注释）
			s += "P\t" + std::to_string(ProxyQuestFormID()) + "\n";
			for (const auto& q : a_quests) {
				std::string zh = q.nameZh;
				std::string en = q.nameEn;
				// ★★ 第 75 轮：说明文本也在载荷里 —— 同样要清掉会破坏列结构/行结构的字符。
				std::string noteZh = q.noteZh;
				std::string noteEn = q.noteEn;
				for (auto* name : { &zh, &en, &noteZh, &noteEn }) {
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
				s += "\t";
				s += q.hasGuideTarget ? "1" : "0";  // ★ 第 23 轮：能不能导航（界面据此置灰/说明）
				s += "\t";
				s += q.needsApproach ? "1" : "0";   // ★ 第 46 轮：全是非常驻候选 ⇒ 需要靠近
				s += "\t";
				s += std::to_string(q.faction);     // ★ 第 65 轮：原版阵营枚举（-1=无阵营）
				// ★★ 第 74 轮（同伴好感度任务）：第 8 列 = 「入口」同伴任务（固定显示）。
				//   界面据此在描述里提示「需要一定好感度才能接取」。
				//   旧版 AS3 / 内嵌回退数据缺这列 ⇒ 按 "0" 处理（不提这回事）。
				s += "\t";
				s += q.companionPinned ? "1" : "0";
				// ★★ 第 75 轮（四大势力开头任务）：第 9/10 列 = 「简要说明」（中 / 英）——
				//   界面把它当描述的第一句（加入方式 / 前置条件）；其余任务是空串。
				//   旧版 AS3 / 内嵌回退数据缺这列 ⇒ 空串（走原来的「当前可以接取」文案）。
				s += "\t";
				s += noteZh;
				s += "\t";
				s += noteEn;
				// ★★ 第 89 轮（可重复任务）：第 11 列 = 可重复标记（"1"/"0"）——
				//   AS3 侧 FilterKnownQuests 据此豁免「在玩家日志里」的丢弃
				//   （已完成 + 可重复 ⇒ 保留；进行中照旧隐藏）。
				//   旧版 AS3 / 内嵌回退数据缺这列 ⇒ 按 false 处理（老行为）。
				s += "\t";
				s += q.repeatable ? "1" : "0";
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
	// ★ 第 16 轮删掉了「裸名字 + 宽字符」的那次对照调用（第 8 轮就用它证明了
	//   「必须带 `_root.` 前缀」）——结论已固化成 kAttempts 的顺序，日志里
	//   每次推送都留一条 `SAQ_Probe=fail` 只会误导看日志的人。
	std::string ProbeAs3String(RE::Scaleform::GFx::ASMovieRootBase* a_root, const char* a_path,
		const std::string& a_utf8)
	{
		RE::Scaleform::GFx::Value arg;
		if (!VtableSlotInModule(a_root, kSlotAsRootCreateString) ||
			!SafeCreateString(a_root, &arg, a_utf8.c_str())) {
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
	// ★ 第 19 轮：缓冲区 512 → 2048。SAQ_Report 里带玩家任务日志名单（qdata=，最多
	//   12 条中文名），512 字节在多任务存档上会把尾部截断，而且可能切在多字节字符
	//   中间（实测日志出现 `0:�`）。
	std::string CallAs3NoArg(RE::Scaleform::GFx::ASMovieRootBase* a_root, const char* a_path)
	{
		RE::Scaleform::GFx::Value ret;
		if (!SafeInvoke(a_root, a_path, &ret, nullptr, 0)) {
			return std::string{ a_path } + "=fail(路径不存在或调用失败)";
		}
		char buf[2048]{};
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
		//   （裸名字那条在旧日志里恒为 fail —— 与 kAttempts 的实测一致：必须带 `_root.` 前缀。）
		const std::string probeS = ProbeAs3String(root, "_root.SAQ_Probe", payloadUtf8);

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
		// ★ 第 19 轮：400 → 900（报告里现在还有 drop= 被过滤名单，别把它截掉）。
		// ★★ 第 84 轮：900 → 1500 —— 第 65/74/75/80 轮又往报告里加了
		//   icon= / order= / pin= / rep= 探针，900 字节实测会在 qdata 名单中间截断
		//   （qdata/drop 是「某条任务为什么没显示」的第一手证据，最不该被截）。
		const std::string report = EscapeForLog(CallAs3NoArg(root, "_root.SAQ_Report"), 1500);

		// 先把解析信息留一份 —— 失败时下面会 Reset()，缓存里的 detail 会被清掉。
		const std::string bridgeDetail = bridge.detail;

		if (!ok) {
			// 全部组合失败：把缓存清掉，下一次重试（或下次开菜单）从「找菜单表」重新来一遍
			// —— 菜单刚开那一两帧 Movie 可能还在换代的中间态，缓存住就没救了。
			Reset();
		}

		a_detail = bridgeDetail + slotNote +
			" 探针: " + EscapeForLog(probeS, 120) +
			" 调用: " + trail +
			std::format(" 载荷={} 字节/{} 条 代理任务=0x{:08X}", payloadUtf8.size(),
				a_quests.size(), ProxyQuestFormID()) +
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
		a_report = EscapeForLog(raw, 1500);  // ★ 第 19 轮：400 → 900；★★ 第 84 轮：→ 1500（同上）
		return true;
	}

	// ★★★ 第 125 轮（路线 D · 冲突检测）：界面身份探测（设计与判据见 SAQ_UI.h）。
	//
	// 为什么用 `SAQ_Report` 而不是 `SAQ_PushData`：SAQ_Report 是 0 参、**每个版本**
	//   我们的 SWF 都挂的入口（第 50 轮起还带 `stamp=` 构建指纹）—— 一次调用同时回答
	//   「入口在不在」与「版本对不对」两个问题；而 SAQ_PushData 的调用失败无法与
	//   「载荷/时序问题」区分。桥解析失败 = 菜单还在创建 ⇒ unknown（不判定、保持重试）。
	ChannelIdentity ProbeChannelIdentity(std::string& a_detail)
	{
		if (!EnsureResolved(a_detail)) {
			return ChannelIdentity::unknown;  // 桥没通：菜单刚开 / 换代中间态 —— 保持重试
		}
		auto& bridge = Cached();
		auto* root = reinterpret_cast<RE::Scaleform::GFx::ASMovieRootBase*>(bridge.asRoot);
		if (!root) {
			a_detail = "ASMovieRoot 指针为空";
			return ChannelIdentity::unknown;
		}
		const std::string raw = CallAs3NoArg(root, "_root.SAQ_Report");
		if (raw.find("=fail") != std::string::npos) {
			a_detail = "_root.SAQ_Report 调用失败（界面里没有我们的入口 —— 原版 / 第三方 / 未挂载）";
			return ChannelIdentity::notOurs;
		}
		const auto at = raw.find("stamp=");
		if (at == std::string::npos) {
			a_detail = "_root.SAQ_Report 可调用但没有 stamp= 指纹（界面是我们的旧版本）";
			return ChannelIdentity::notOurs;
		}
		const auto sp = raw.find(' ', at);
		a_detail = "_root.SAQ_Report 带指纹 stamp=" +
			raw.substr(at + 6, sp == std::string::npos ? std::string::npos : sp - at - 6);
		return ChannelIdentity::ours;
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

	namespace
	{
		// ★ 第 16 轮：Invoke 一个「单字符串参数」的 AS3 函数，并把字符串应答读回来。
		// 与 PushAvailableQuests 的传参方式一致（宽字符 Value：中文/ASCII 都不经过编码转换）。
		// 返回 true = 调用发出（a_reply = AS3 应答）；false = 桥没通 / 函数不存在（旧 SWF）。
		bool CallAs3WithString(RE::Scaleform::GFx::ASMovieRootBase* a_root, const char* a_path,
			const char* a_argUtf8, std::string& a_reply)
		{
			const std::wstring wide = Utf8ToWide(a_argUtf8);
			if (wide.empty()) {
				a_reply = "参数编码失败";
				return false;
			}
			RE::Scaleform::GFx::Value arg(wide.c_str());
			RE::Scaleform::GFx::Value ret;
			if (!SafeInvoke(a_root, a_path, &ret, &arg, 1)) {
				a_reply = std::string{ a_path } + "=fail(路径不存在或调用失败)";
				return false;
			}
			char buf[96]{};
			if (SafeReadValueString(ret, buf, sizeof(buf))) {
				a_reply = buf;
			} else {
				a_reply.clear();  // 调用成功但没返回字符串（函数的返回值是 undefined 之类）
			}
			return true;
		}
	}

	// ★ 第 16 轮：引导结果回写（协议见 SAQ_UI.h 与 MissionMenu.as 的 SAQ_GuideReply）。
	bool NotifyGuideReply(int a_seq, std::uint32_t a_actualFormID, int a_code, std::string& a_reply)
	{
		std::string detail;
		if (!EnsureResolved(detail)) {
			a_reply = "桥没通";
			return false;
		}
		auto& bridge = Cached();
		auto* root = reinterpret_cast<RE::Scaleform::GFx::ASMovieRootBase*>(bridge.asRoot);
		if (!root) {
			a_reply = "ASMovieRoot 指针为空";
			return false;
		}
		const std::string arg = std::format("{}|{}|{}", a_seq, a_actualFormID, a_code);
		return CallAs3WithString(root, "_root.SAQ_GuideReply", arg.c_str(), a_reply);
	}

	// ★ 第 16 轮：把「当前实际引导任务」同步给界面（见 SAQ_UI.h）。
	bool SyncGuideState(std::uint32_t a_formID, std::string& a_reply)
	{
		std::string detail;
		if (!EnsureResolved(detail)) {
			a_reply = "桥没通";
			return false;
		}
		auto& bridge = Cached();
		auto* root = reinterpret_cast<RE::Scaleform::GFx::ASMovieRootBase*>(bridge.asRoot);
		if (!root) {
			a_reply = "ASMovieRoot 指针为空";
			return false;
		}
		const std::string arg = std::to_string(a_formID);
		return CallAs3WithString(root, "_root.SAQ_SyncGuideState", arg.c_str(), a_reply);
	}

#if SAQ_WITH_HARNESS
	// ★★ 第 49 轮（harness）：把「测试驱动」调用发给 AS3 的 SAQ_TestDrive* 入口。
	//
	// ★ 第 53 轮（大项 F · 发布就绪）：整个函数只在开发构建（SAQ_WITH_HARNESS=1）里存在 ——
	//   发布构建的 DLL 里不该出现 `SAQ_TestDrive*` / 「SWF 指纹」这类测试期字符串。
	//   AS3 侧的那几个入口（SWF 里）保留：它们只在 DLL 主动调用时才起作用，
	//   而发布版 DLL 已不存在任何调用路径（见 docs/09 的发布构建一节）。
	//
	// 用途：引擎内自动测试要代替人做「选中某条 / 按 R / 展开子项」这些操作 ——
	// 用的是**同一条 Invoke 通道**（本项目已经跑了十几轮的那条），所以不需要键鼠、
	// 也不会抢玩家的输入（AGENTS.md 的要求）。
	//
	// ★ 关键约定：AS3 侧那几个入口**必须调用真实的处理函数**（选中变化 / 按键处理 /
	//   展开），不许复制一套逻辑 —— 否则测的是测试代码，不是产品代码。
	//   返回串是 AS3 给的短状态（如 "ok|idx=3" / "err|notfound"），进结果 JSON 当证据。
	bool InvokeUiTestDrive(const char* a_fn, const std::string& a_arg, std::string& a_reply)
	{
		if (!a_fn || !*a_fn) {
			a_reply = "空函数名";
			return false;
		}
		std::string detail;
		if (!EnsureResolved(detail)) {
			a_reply = "桥没通";
			return false;
		}
		auto& bridge = Cached();
		auto* root = reinterpret_cast<RE::Scaleform::GFx::ASMovieRootBase*>(bridge.asRoot);
		if (!root) {
			a_reply = "ASMovieRoot 指针为空";
			return false;
		}
		// 缓冲区比 CallAs3WithString 的大（那个是 96）：测试入口会回一行诊断，
		// 可能带任务名（中文）与下标，96 字节会被截断在多字节字符中间。
		const std::wstring wide = Utf8ToWide(a_arg.c_str());
		if (wide.empty() && !a_arg.empty()) {
			a_reply = "参数编码失败";
			return false;
		}
		// ★ 第 49 轮补丁：**实参个数必须与 AS3 签名一致**。
		//   首测实证（smoke 卡在 ui.tab）：`SAQ_TestDriveTab()` 是 0 参，而我们传了
		//   1 个参数（空字符串占位）⇒ Invoke **直接失败**（耗时 0 ms，
		//   `_root.SAQ_TestDriveTab=fail(路径不存在或调用失败)`）。
		//   同一个 `_root` 上的对照：0 参的 `SAQ_Report` 用 0 参调用一直成功
		//   （每 500ms 轮询在读），1 参的 `SAQ_Probe` 用 1 参调用也成功
		//   ⇒ 无参入口必须走 0 参调用，不能拿空字符串占位。
		//
		// ★★ 第 51 轮：调用路径改成**多条尝试**（原来只有 `_root.<fn>` 一条）——
		//   起因：06:34 会话 SWF 已带 stamp=50（新构建、挂载字节码经 FFDec 验证在）、
		//   0 参调用也正确，ui.tab 仍 0 ms 失败；C++ 侧必须先把「路径写法」这一层
		//   自证干净：与推送同风格，按 裸名 / `_root.` / `_root.root.` 依次试，
		//   失败详情里列出每一条的结果（成功走非首选写法时补一行 INFO 日志）。
		const char* const kPathPrefixes[] = { "_root.", "", "_root.root." };
		RE::Scaleform::GFx::Value ret;
		std::string tried;
		std::string usedPath;
		bool called = false;
		for (const char* prefix : kPathPrefixes) {
			const std::string path = std::string{ prefix } + a_fn;
			bool thisCalled = false;
			if (a_arg.empty()) {
				thisCalled = SafeInvoke(root, path.c_str(), &ret, nullptr, 0);
			} else {
				RE::Scaleform::GFx::Value arg(wide.c_str());
				thisCalled = SafeInvoke(root, path.c_str(), &ret, &arg, 1);
			}
			tried += (tried.empty() ? "" : "｜");
			tried += path + (thisCalled ? "=ok" : "=fail");
			if (thisCalled) {
				usedPath = path;
				called = true;
				break;
			}
		}
		if (called && usedPath != std::string{ "_root." } + a_fn) {
			REX::INFO("测试驱动：{} 用写法 {} 调用成功（首选 `_root.` 前缀失败）", a_fn, usedPath);
		}
		if (!called) {
			// ★★ 第 50 轮：失败时顺便把「游戏加载的 SWF 是新版还是旧版」带出来 ——
			//   起因：第 49 轮补丁③ 的产物经字节码级验证（FFDec P-code）无误，
			//   22:48 会话 ui.tab 仍 0 ms 失败 ⇒ 证据指向「游戏加载的仍是部署前的旧
			//   SWF」（Starfield 的 UI 资源在**游戏启动阶段**加载，早于 SFSE 插件加载
			//   日志的时刻；补丁③是在游戏进程启动之后才构建部署的）。
			//   这里读一次 SAQ_Report（0 参、已挂载、一直可用的入口）：
			//     有 `stamp=` 字段 = SWF 是带指纹的新版 ⇒ 失败另有其因；
			//     没有              = 游戏加载的是旧版 SWF ⇒ 完全重启游戏后可解。
			a_reply = tried + "｜(各写法都失败：路径不存在或调用失败；SWF 是旧版？)";
			const auto report = CallAs3NoArg(root, "_root.SAQ_Report");
			const auto at = report.find("stamp=");
			if (at != std::string::npos) {
				a_reply += "｜SWF 指纹=" + report.substr(at + 6, 8) +
					"（新版 SWF 已加载 ⇒ 失败与 SWF 版本无关）";
			} else {
				a_reply += "｜SWF 指纹：SAQ_Report 里没有 stamp= 字段"
					"（⇒ 游戏加载的还是旧版 SWF；完全重启游戏后再跑）";
			}
			// ★ 第 51 轮：界面侧入口自检（ep=）也带出来 ——
			//   一眼分清「挂载没跑到 / root 上取不到入口 / 全在但 Invoke 仍失败」。
			const auto epAt = report.find("ep=");
			if (epAt != std::string::npos) {
				const auto epEnd = report.find(' ', epAt);
				a_reply += "｜入口自检=" + report.substr(epAt,
					epEnd == std::string::npos ? std::string::npos : epEnd - epAt);
			}
			return false;
		}
		char buf[512]{};
		if (SafeReadValueString(ret, buf, sizeof(buf))) {
			a_reply = buf;
		} else {
			a_reply.clear();
		}
		return true;
	}

	// ======================================================================
	// ★★★ 第 117 轮（无 SWF 覆盖的 UI 注入研究 · docs/15）：`ui.research` 探针
	//
	//   验证"不替换 missionmenu.swf、直接在运行时操作原版 AS3 对象"的可行性
	//   （目的 = 消除与其它改任务菜单 UI mod 的文件级二选一冲突）。三个未知点：
	//
	//     U1 私有成员可读写性 —— `_root.Menu_mc.FilterInfoA`（原版 private；
	//        只有 3 处使用：声明 / currentFilterFlag / PopulateTabs）。它决定
	//        "第 8 个 tab"能否存在：不写它，`currentFilterFlag` 在选中第 8 个
	//        tab 时会越界（原版 MissionMenu.as:171/347）。
	//     U2 public 方法/属性 —— `TabbedFilterSelection_mc.SetTabsData(Array)`
	//        （BSTabbedSelection.as:141，public）+ `numTabs`（getter）。
	//     U3 事件注入 —— `MissionsList_mc.addEventListener("MissionsList::itemActivated",
	//        <C++ FunctionHandler>)`（事件名是 public static const，可硬编码）。
	//
	//   方法论（与项目其余探针一致）：**每个动作"调用 → 读回验证"**，不能只看
	//   调用返回值；结果汇总成一行产品日志（`界面研究探针 …`，可被 assert.log 取证）。
	//
	//   副作用：写测试会往 `FilterInfoA` 追加一个标记项（幂等：已有就跳过）——
	//   菜单关闭后 Movie 销毁、下次打开重建（第 27/50 轮定案）⇒ 天然清理。
	// ======================================================================
	namespace
	{
		constexpr std::size_t kSlotAsRootCreateObject = 0x2E;    // CreateObject(Value*, const char* = nullptr, …)
		constexpr std::size_t kSlotAsRootCreateArray = 0x2F;     // CreateArray(Value*)
		constexpr std::size_t kSlotAsRootCreateFunction = 0x30;  // CreateFunction(Value*, FunctionHandler*, void*)
		constexpr std::size_t kSlotAsRootGetVariable = 0x32;     // GetVariable(Value*, const char*) const

		constexpr const char*   kResearchMarkText = "SAQ研究";        // 写测试标记项（幂等识别）
		constexpr std::uint32_t kResearchMarkFlag = 1u << 6;          // = 1 << AVAILABLE_QUEST_TYPE（64）

		bool SafeGetVariable(RE::Scaleform::GFx::ASMovieRootBase* a_root, const char* a_path,
			RE::Scaleform::GFx::Value* a_out)
		{
			__try {
				return a_root->GetVariable(a_out, a_path);
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				return false;
			}
		}

		bool SafeCreateObject(RE::Scaleform::GFx::ASMovieRootBase* a_root, RE::Scaleform::GFx::Value* a_out)
		{
			__try {
				a_root->CreateObject(a_out);
				return true;
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				return false;
			}
		}

		bool SafeCreateFunction(RE::Scaleform::GFx::ASMovieRootBase* a_root, RE::Scaleform::GFx::Value* a_out,
			RE::Scaleform::GFx::FunctionHandler* a_handler, void* a_userData)
		{
			__try {
				a_root->CreateFunction(a_out, a_handler, a_userData);
				return true;
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				return false;
			}
		}

		bool SafeValueGetMember(RE::Scaleform::GFx::Value* a_obj, const char* a_name,
			RE::Scaleform::GFx::Value* a_out)
		{
			__try {
				return a_obj->GetMember(a_name, a_out);
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				return false;
			}
		}

		bool SafeValueSetMember(RE::Scaleform::GFx::Value* a_obj, const char* a_name,
			const RE::Scaleform::GFx::Value& a_value)
		{
			__try {
				return a_obj->SetMember(a_name, a_value);
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				return false;
			}
		}

		bool SafeValueInvoke(RE::Scaleform::GFx::Value* a_obj, const char* a_name,
			RE::Scaleform::GFx::Value* a_result, RE::Scaleform::GFx::Value* a_args, std::size_t a_count)
		{
			__try {
				return a_obj->Invoke(a_name, a_result, a_args, a_count);
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				return false;
			}
		}

		bool SafeValuePushBack(RE::Scaleform::GFx::Value* a_arr, const RE::Scaleform::GFx::Value& a_value)
		{
			__try {
				return a_arr->PushBack(a_value);
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				return false;
			}
		}

		bool SafeValueVisitElements(RE::Scaleform::GFx::Value* a_arr,
			RE::Scaleform::GFx::Value::ObjectInterface::ArrVisitor* a_visitor)
		{
			__try {
				a_arr->VisitElements(a_visitor);
				return true;
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				return false;
			}
		}

		// `FilterInfoA` 的项形状 = {text:String, flag:uint} —— 逐项收集摘要。
		// 上限 16 项（正常 7~9；多了说明结构变了，别把日志刷爆）。
		class FilterInfoScanVisitor : public RE::Scaleform::GFx::Value::ObjectInterface::ArrVisitor
		{
		public:
			void Visit(std::uint32_t a_idx, const RE::Scaleform::GFx::Value& a_val) override
			{
				(void)a_idx;
				if (count >= kMax) {
					overflow = true;
					return;
				}
				++count;
				char text[64]{};
				RE::Scaleform::GFx::Value t;
				if (a_val.GetMember("text", &t)) {
					(void)SafeReadValueString(t, text, sizeof(text));
				}
				if (text[0] == '\0') {
					std::snprintf(text, sizeof(text), "?");
				}
				RE::Scaleform::GFx::Value f;
				double                    flag = 0.0;
				const bool hasFlag = a_val.GetMember("flag", &f) && SafeReadValueNumber(f, flag);
				if (std::strcmp(text, kResearchMarkText) == 0) {
					hasOurMark = true;
				}
				if (count <= kMaxDetail) {
					if (!summary.empty()) {
						summary += "，";
					}
					summary += std::format("{}.{}{}", count - 1, text,
						hasFlag ? std::format("/0x{:X}", static_cast<std::uint64_t>(flag)) : std::string{});
				}
			}

			std::int32_t count{};
			bool         overflow{};
			bool         hasOurMark{};
			std::string  summary;

		private:
			static constexpr std::int32_t kMax = 16;
			static constexpr std::int32_t kMaxDetail = 8;
		};

		// U3 用：事件回调 handler（只计数 + 留一行日志；参数解析留待后续轮次）。
		// 生命周期：堆分配（RefCountBase 初始 0；`CreateFunction` / 事件系统会 AddRef，
		// AS3 侧释放时 Release → 0 → delete）—— 静态对象会被 Release 误删，不能用 static。
		class ResearchEventHandler : public RE::Scaleform::GFx::FunctionHandler
		{
		public:
			void Call(const Params& a_params) override
			{
				const int n = ++s_calls;
				REX::INFO("界面研究探针：事件回调收到（第 {} 次，argCount={}）", n, a_params.argCount);
			}

			static std::atomic<int> s_calls;
		};
		std::atomic<int> ResearchEventHandler::s_calls{ 0 };
	}

	std::string ResearchGfxCapabilities(bool a_withEvents)
	{
		std::string detail;
		if (!EnsureResolved(detail)) {
			return "桥没通（" + EscapeForLog(detail, 200) + "）";
		}
		auto& bridge = Cached();
		auto* root = reinterpret_cast<RE::Scaleform::GFx::ASMovieRootBase*>(bridge.asRoot);
		if (!root) {
			return "ASMovieRoot 指针为空";
		}

		std::string out;

		// ---- U0：路径读基础设施（GetVariable 槽 —— commonlibsf 标 0x32，本版本未验证）----
		const bool getVarSlot = VtableSlotInModule(root, kSlotAsRootGetVariable);
		RE::Scaleform::GFx::Value menu;  // `_root.Menu_mc` = MissionMenu 实例（原版/我们的 SWF 同名）
		bool menuOk = false;
		if (getVarSlot) {
			menuOk = SafeGetVariable(root, "_root.Menu_mc", &menu) && menu.IsObject();
		}
		out += std::format("GetVar槽={}｜Menu_mc={}", getVarSlot ? "在" : "无", menuOk ? "ok" : "fail");
		if (!menuOk) {
			return out + "（后面各项依赖它，本轮到此为止）";
		}

		// ---- U1 读：`FilterInfoA`（原版 private）----
		RE::Scaleform::GFx::Value fi;
		const bool hasMember = menu.HasMember("FilterInfoA");
		const bool readOk = SafeValueGetMember(&menu, "FilterInfoA", &fi) && fi.IsArray();
		FilterInfoScanVisitor scan;
		if (readOk) {
			(void)SafeValueVisitElements(&fi, &scan);
		}
		out += std::format("｜私有读=({} HasMember={} 项数={}{})",
			readOk ? "ok" : "fail", hasMember ? 1 : 0, scan.count, scan.overflow ? " 溢出16+" : "");
		if (!scan.summary.empty()) {
			out += "｜内容=" + EscapeForLog(scan.summary, 220);
		}

		// ---- U1 写：往数组追加标记项（引用修改；幂等）----
		bool         writeOk = false;
		std::int32_t afterWrite = -1;
		if (readOk && !scan.hasOurMark) {
			RE::Scaleform::GFx::Value item;
			const bool created = VtableSlotInModule(root, kSlotAsRootCreateObject) && SafeCreateObject(root, &item);
			bool marked = false;
			if (created) {
				RE::Scaleform::GFx::Value title;
				if (SafeCreateString(root, &title, kResearchMarkText)) {
					(void)SafeValueSetMember(&item, "text", title);
				}
				RE::Scaleform::GFx::Value flag(static_cast<std::uint32_t>(kResearchMarkFlag));
				(void)SafeValueSetMember(&item, "flag", flag);
				marked = SafeValuePushBack(&fi, item);
			}
			// 读回验证（不能只看 PushBack 的返回值）
			RE::Scaleform::GFx::Value fi2;
			if (SafeValueGetMember(&menu, "FilterInfoA", &fi2) && fi2.IsArray()) {
				FilterInfoScanVisitor scan2;
				(void)SafeValueVisitElements(&fi2, &scan2);
				afterWrite = scan2.count;
				writeOk = marked && scan2.count == scan.count + 1 && scan2.hasOurMark;
			}
			out += std::format("｜私有写={}（{}→{}）", writeOk ? "ok" : "fail", scan.count, afterWrite);
		} else if (readOk) {
			writeOk = true;  // 已有标记项（上一次已写过）—— 视为可写
			out += std::format("｜私有写=已验证（已有标记项，共{}项）", scan.count);
		} else {
			out += "｜私有写=未做（读失败）";
		}

		// ---- U2：`TabbedFilterSelection_mc.SetTabsData` + `numTabs` 读回 ----
		RE::Scaleform::GFx::Value tabSel;
		const bool tabSelOk = SafeValueGetMember(&menu, "TabbedFilterSelection_mc", &tabSel) && tabSel.IsObject();
		double tabsBefore = -1.0;
		if (tabSelOk) {
			RE::Scaleform::GFx::Value nt;
			if (SafeValueGetMember(&tabSel, "numTabs", &nt)) {
				(void)SafeReadValueNumber(nt, tabsBefore);
			}
		}
		out += std::format("｜TabSel={} numTabs={}", tabSelOk ? "ok" : "fail",
			tabsBefore >= 0 ? std::format("{:.0f}", tabsBefore) : std::string{ "?" });
		if (tabSelOk && writeOk && readOk) {
			RE::Scaleform::GFx::Value arg = fi;  // 同一 AS3 数组（引用语义）
			RE::Scaleform::GFx::Value ret;
			const bool called = SafeValueInvoke(&tabSel, "SetTabsData", &ret, &arg, 1);
			RE::Scaleform::GFx::Value nt2;
			double                   tabsAfter = -1.0;
			if (SafeValueGetMember(&tabSel, "numTabs", &nt2)) {
				(void)SafeReadValueNumber(nt2, tabsAfter);
			}
			const bool ok = called && tabsAfter == tabsBefore + 1;
			out += std::format("｜SetTabsData={}（numTabs {}→{}）", ok ? "ok" : "fail",
				tabsBefore >= 0 ? std::format("{:.0f}", tabsBefore) : std::string{ "?" },
				tabsAfter >= 0 ? std::format("{:.0f}", tabsAfter) : std::string{ "?" });
		}

		// ---- U3：事件注入（可选，单独一步便于定位）----
		if (!a_withEvents) {
			out += "｜事件=未试";
			return out;
		}
		RE::Scaleform::GFx::Value list;
		const bool listOk = SafeValueGetMember(&menu, "MissionsList_mc", &list) && list.IsObject();
		out += std::format("｜MissionsList_mc={}", listOk ? "ok" : "fail");
		if (listOk && VtableSlotInModule(root, kSlotAsRootCreateFunction)) {
			RE::Scaleform::GFx::Value fn;
			if (SafeCreateFunction(root, &fn, new ResearchEventHandler(), nullptr)) {
				RE::Scaleform::GFx::Value title;
				if (!SafeCreateString(root, &title, "MissionsList::itemActivated")) {
					return out + "｜事件注册=事件名编码失败";
				}
				RE::Scaleform::GFx::Value args[5];
				args[0] = title;
				args[1] = fn;
				args[2] = false;
				args[3] = static_cast<std::uint32_t>(100);  // priority（原版监听器 priority = 0）
				args[4] = false;
				RE::Scaleform::GFx::Value ret;
				const bool added = SafeValueInvoke(&list, "addEventListener", &ret, args, 5);
				out += std::format("｜事件注册={}（点列表条目后看「事件回调收到」）", added ? "ok" : "fail");
			} else {
				out += "｜事件注册=fail（CreateFunction 失败）";
			}
		} else {
			out += "｜事件注册=未做（列表取不到 / CreateFunction 槽不在）";
		}
		return out;
	}

	// ======================================================================
	// ★★★ 第 119 轮（探针 v2 / P1.5 · docs/15 九·补）：`ui.research2`
	//
	//   第 118 轮判明：U1（private 成员读写）**读不到**（`HasMember=0`）——
	//   AVM2 的 private trait 带类私有 namespace，GFx 的 public multiname 查不到。
	//   ⇒ 本轮验证「**不碰 FilterInfoA** 的绕过路径」—— 这才是产品形态要用的：
	//
	//     R1 成员枚举：ObjVisitor 扫 `Menu_mc`（尽力模式，含 AS3 public 链）——
	//        FilterInfoA 是否可见（收口取证；预期不可见 ⇒ 彻底关闭这条读取路）。
	//     R2 事件拦截：在 `TabbedFilterSelection_mc` 挂 priority=100 的
	//        `"BSTabbedSelection::selectionChange"` 监听（原版 onFilterChanged
	//        是同一事件上的 priority=0 监听）—— handler 对 iSelectedIndex==7
	//        （我们的 tab）`stopImmediatePropagation()`（防原版 `FilterInfoA[7]` 越界）。
	//     R3 `filterMask` 写：拦截时用 SetMember 自设**哨兵值**（1<<29）并读回 ——
	//        原版（priority=0）若没被拦住会在我们之后执行、把值覆盖回自己的 flag
	//        ⇒ **哨兵存活 = 拦截生效 + 写生效**（单值双判据）。
	//     R4 U2 补测：C++ 构造数组 → `SetTabsData` → `numTabs` 读回（N→N+1→N；
	//        第 118 轮把它错误地耦合在 U1 之后 —— 它其实**不依赖 FilterInfoA**）。
	//
	//   切 tab 走原版 public 入口 `MissionTabbedSelection.SetSelectedCategoryIndex`
	//   （内部 `SetSelectedIndex` → `dispatchEvent`；原版「读档恢复上次分类」用的
	//   就是它）：切 3 → 原版执行（对照：mask 变）；切 7 → 被拦（mask=哨兵）；
	//   切 0 → 放行（mask 回 `$ALL`）。四段一次跑完，结果一行汇总（红线六）。
	// ======================================================================
	namespace
	{
		constexpr std::uint32_t kResearch2InterceptIndex = 7;       // 我们的 tab（第 8 个）下标
		constexpr std::uint32_t kResearch2SentinelMask = 1u << 29;  // 哨兵（原版/我们都不会用的 flag 位）
		constexpr const char*   kResearch2EventName = "BSTabbedSelection::selectionChange";

		bool SafeCreateArray(RE::Scaleform::GFx::ASMovieRootBase* a_root, RE::Scaleform::GFx::Value* a_out)
		{
			__try {
				a_root->CreateArray(a_out);
				return true;
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				return false;
			}
		}

		bool SafeValueVisitMembers(RE::Scaleform::GFx::Value* a_obj,
			RE::Scaleform::GFx::Value::ObjectVisitor* a_visitor)
		{
			__try {
				a_obj->VisitMembers(a_visitor);
				return true;
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				return false;
			}
		}

		// R1 用：扫对象成员（尽力模式）—— 只统计总数 + 找 FilterInfoA（不做字符串表）。
		class MemberScanVisitor : public RE::Scaleform::GFx::Value::ObjectVisitor
		{
		public:
			bool IncludeAS3PublicMembers() const override { return true; }

			void Visit(const char* a_name, const RE::Scaleform::GFx::Value& a_val) override
			{
				(void)a_val;
				++count;
				if (a_name && std::strcmp(a_name, "FilterInfoA") == 0) {
					foundFilterInfoA = true;
				}
			}

			std::int32_t count{};
			bool         foundFilterInfoA{};
		};

		// R2/R3 用：拦截 handler —— 读事件里的 `iSelectedIndex`；== 我们的 tab（7）时
		//   `stopImmediatePropagation()` + 自设 `filterMask` 哨兵（读回验证）。
		//   生命周期同第 117 轮：堆分配（RefCountBase 初始 0；事件系统 AddRef，
		//   `removeEventListener` 后 Release → 0 → delete）⇒ **remove 之后绝不能再
		//   解引用**（统计必须在 remove 前抄走）。
		class Research2EventHandler : public RE::Scaleform::GFx::FunctionHandler
		{
		public:
			explicit Research2EventHandler(RE::Scaleform::GFx::Value a_missionsList) :
				m_missionsList(a_missionsList)  // 拷贝（AddRef）—— 只在本次菜单生命周期内用
			{}

			void Call(const Params& a_params) override
			{
				int idx = -1;
				if (a_params.argCount >= 1 && a_params.args) {
					RE::Scaleform::GFx::Value iv;
					double                  d = -1.0;
					if (a_params.args[0].GetMember("iSelectedIndex", &iv) && SafeReadValueNumber(iv, d)) {
						idx = static_cast<int>(d);
					}
				}
				const int n = ++s_calls;
				s_lastIndex = idx;
				bool stopped = false;
				if (idx == static_cast<int>(kResearch2InterceptIndex) && a_params.argCount >= 1 && a_params.args) {
					// 拦住原版 onFilterChanged（priority=0）—— 不拦的话它随后执行
					//   `filterMask = FilterInfoA[7].flag`（原版越界 TypeError）。
					RE::Scaleform::GFx::Value ret;
					(void)SafeValueInvoke(&a_params.args[0], "stopImmediatePropagation", &ret, nullptr, 0);
					RE::Scaleform::GFx::Value sentinel(static_cast<std::uint32_t>(kResearch2SentinelMask));
					const bool wrote = SafeValueSetMember(&m_missionsList, "filterMask", sentinel);
					// 读回验证（不能只看 SetMember 返回值）
					RE::Scaleform::GFx::Value back;
					double                  backNum = -1.0;
					const bool readBack = SafeValueGetMember(&m_missionsList, "filterMask", &back) &&
						SafeReadValueNumber(back, backNum);
					stopped = wrote && readBack &&
						static_cast<std::uint32_t>(backNum) == kResearch2SentinelMask;
					if (stopped) {
						++s_blocks;
					}
				}
				s_lastStopped = stopped;
				REX::INFO("界面研究探针2：事件回调（第 {} 次 idx={} 拦截={}）", n, idx, stopped ? "是" : "否");
			}

			static std::atomic<int>  s_calls;
			static std::atomic<int>  s_blocks;
			static std::atomic<int>  s_lastIndex;
			static std::atomic<bool> s_lastStopped;

		private:
			RE::Scaleform::GFx::Value m_missionsList;
		};
		std::atomic<int>  Research2EventHandler::s_calls{ 0 };
		std::atomic<int>  Research2EventHandler::s_blocks{ 0 };
		std::atomic<int>  Research2EventHandler::s_lastIndex{ -1 };
		std::atomic<bool> Research2EventHandler::s_lastStopped{ false };

		std::string Research2MaskHex(double a_mask)
		{
			if (a_mask < 0.0) {
				return "?";
			}
			return std::format("0x{:08X}", static_cast<std::uint32_t>(static_cast<std::uint64_t>(a_mask)));
		}

		std::string Research2NumStr(double a_v)
		{
			if (a_v < 0.0) {
				return "?";
			}
			return std::format("{:.0f}", a_v);
		}
	}

	std::string ResearchGfxInjection2()
	{
		std::string detail;
		if (!EnsureResolved(detail)) {
			return "桥没通（" + EscapeForLog(detail, 200) + "）";
		}
		auto& bridge = Cached();
		auto* root = reinterpret_cast<RE::Scaleform::GFx::ASMovieRootBase*>(bridge.asRoot);
		if (!root) {
			return "ASMovieRoot 指针为空";
		}

		std::string out;

		RE::Scaleform::GFx::Value menu;
		const bool menuOk = SafeGetVariable(root, "_root.Menu_mc", &menu) && menu.IsObject();
		if (!menuOk) {
			return "Menu_mc=fail（路径取不到，后面全部依赖它）";
		}
		out += "Menu_mc=ok";

		// ---- R1：成员枚举（尽力模式）----
		{
			MemberScanVisitor scan;
			const bool scanned = SafeValueVisitMembers(&menu, &scan);
			out += std::format("｜枚举=({}{} 个,FilterInfoA={})",
				scanned ? "" : "fail ", scan.count, scan.foundFilterInfoA ? "有" : "无");
		}

		RE::Scaleform::GFx::Value tabSel;
		RE::Scaleform::GFx::Value list;
		const bool tabSelOk = SafeValueGetMember(&menu, "TabbedFilterSelection_mc", &tabSel) && tabSel.IsObject();
		const bool listOk = SafeValueGetMember(&menu, "MissionsList_mc", &list) && list.IsObject();
		if (!tabSelOk || !listOk) {
			return out + std::format("｜TabSel={} MissionsList={}（缺一个就做不下去）",
				tabSelOk ? "ok" : "fail", listOk ? "ok" : "fail");
		}

		auto readMask = [&list](double& a_out) -> bool {
			RE::Scaleform::GFx::Value v;
			return SafeValueGetMember(&list, "filterMask", &v) && SafeReadValueNumber(v, a_out);
		};
		// 原版 public 入口（内部 SetSelectedIndex → dispatchEvent）—— 与原版
		// 「读档恢复上次分类」同一条路。
		auto switchTab = [&tabSel](std::uint32_t a_idx) -> bool {
			RE::Scaleform::GFx::Value arg(static_cast<std::uint32_t>(a_idx));
			RE::Scaleform::GFx::Value ret;
			return SafeValueInvoke(&tabSel, "SetSelectedCategoryIndex", &ret, &arg, 1);
		};

		// ---- R2：挂拦截监听（priority=100；原版 onFilterChanged 是 0）----
		auto* handler = new Research2EventHandler(list);
		RE::Scaleform::GFx::Value fn;
		if (!(VtableSlotInModule(root, kSlotAsRootCreateFunction) &&
				SafeCreateFunction(root, &fn, handler, nullptr))) {
			return out + "｜事件=注册失败（CreateFunction）";
		}
		RE::Scaleform::GFx::Value evTitle;
		if (!SafeCreateString(root, &evTitle, kResearch2EventName)) {
			return out + "｜事件=注册失败（事件名编码失败）";
		}
		{
			RE::Scaleform::GFx::Value args[5];
			args[0] = evTitle;
			args[1] = fn;
			args[2] = false;
			args[3] = static_cast<std::uint32_t>(100);
			args[4] = false;
			RE::Scaleform::GFx::Value ret;
			if (!SafeValueInvoke(&tabSel, "addEventListener", &ret, args, 5)) {
				return out + "｜事件=注册失败（addEventListener）";
			}
		}

		// ---- 四段：读初值 → 切 3（对照）→ 切 7（拦截）→ 切 0（放行）----
		double     mask0 = -1.0, maskA = -1.0, maskB = -1.0, maskC = -1.0;
		const bool r0 = readMask(mask0);
		const bool s3 = switchTab(3);
		const bool rA = readMask(maskA);
		const bool s7 = switchTab(7);
		const bool rB = readMask(maskB);
		const bool s0 = switchTab(0);
		const bool rC = readMask(maskC);
		// 统计先抄走（removeEventListener 之后 handler 可能被 delete，绝不再解引用）
		const int calls = Research2EventHandler::s_calls.load();
		const int blocks = Research2EventHandler::s_blocks.load();
		const int lastIdx = Research2EventHandler::s_lastIndex.load();

		// 判据：切 3 = 回调 + 未被拦 + mask 变化；切 7 = 拦截计数 +1 + mask == 哨兵
		//   （原版若没被拦住，随后执行会把 mask 覆盖回自己的 flag ⇒ 哨兵不存活）；
		//   切 0 = 回到非哨兵（原版执行 `$ALL`）。
		const bool pass3 = s3 && r0 && rA && maskA != mask0 &&
			maskA != static_cast<double>(kResearch2SentinelMask);
		const bool pass7 = s7 && rB && blocks >= 1 &&
			maskB == static_cast<double>(kResearch2SentinelMask);
		const bool pass0 = s0 && rC && maskC != static_cast<double>(kResearch2SentinelMask) && maskC != maskB;
		out += std::format("｜切3={}（mask {}→{}）", pass3 ? "ok" : "fail",
			Research2MaskHex(mask0), Research2MaskHex(maskA));
		out += std::format("｜切7={}（拦截 {} 次,mask→{}）", pass7 ? "ok" : "fail",
			blocks, Research2MaskHex(maskB));
		out += std::format("｜切0={}（mask→{}）", pass0 ? "ok" : "fail", Research2MaskHex(maskC));
		out += std::format("｜回调={} 次（末次 idx={}）", calls, lastIdx);

		// ---- 清理监听（remove 之后 handler 生命周期归 GFx；不再触碰）----
		bool removed = false;
		{
			RE::Scaleform::GFx::Value remArgs[2];
			remArgs[0] = evTitle;
			remArgs[1] = fn;
			RE::Scaleform::GFx::Value ret;
			removed = SafeValueInvoke(&tabSel, "removeEventListener", &ret, remArgs, 2);
		}
		out += std::format("｜清理={}", removed ? "ok" : "fail");

		// ---- R4：U2 补测（SetTabsData 不依赖 FilterInfoA；破坏性 —— 放最后）----
		auto readNumTabs = [&tabSel](double& a_out) -> bool {
			RE::Scaleform::GFx::Value v;
			return SafeValueGetMember(&tabSel, "numTabs", &v) && SafeReadValueNumber(v, a_out);
		};
		auto buildTabs = [&](std::uint32_t a_count, const char* a_tag) -> bool {
			RE::Scaleform::GFx::Value arr;
			if (!(VtableSlotInModule(root, kSlotAsRootCreateArray) && SafeCreateArray(root, &arr))) {
				return false;
			}
			for (std::uint32_t i = 0; i < a_count; ++i) {
				RE::Scaleform::GFx::Value item;
				if (!SafeCreateObject(root, &item)) {
					return false;
				}
				RE::Scaleform::GFx::Value t;
				if (SafeCreateString(root, &t, std::format("${}{}", a_tag, i).c_str())) {
					(void)SafeValueSetMember(&item, "text", t);
				}
				RE::Scaleform::GFx::Value f(static_cast<std::uint32_t>(
					i == 0 ? 0xFFFFFFFFu : (1u << (i % 7))));
				(void)SafeValueSetMember(&item, "flag", f);
				if (!SafeValuePushBack(&arr, item)) {
					return false;
				}
			}
			RE::Scaleform::GFx::Value ret;
			return SafeValueInvoke(&tabSel, "SetTabsData", &ret, &arr, 1);
		};
		double     tabsBefore = -1.0, tabs9 = -1.0, tabs8 = -1.0;
		const bool t0 = readNumTabs(tabsBefore);
		const bool c9 = t0 && buildTabs(9, "SAQ测试");
		const bool t9 = c9 && readNumTabs(tabs9);
		const bool c8 = (t9 && tabs9 == tabsBefore + 1) && buildTabs(8, "SAQ恢复");
		const bool t8 = c8 && readNumTabs(tabs8);
		const bool passU2 = t0 && c9 && t9 && c8 && t8 &&
			tabs9 == tabsBefore + 1 && tabs8 == tabsBefore;
		if (passU2) {
			out += std::format("｜U2=ok（TabsData 调用 ok，numTabs {}→{}→{}）",
				Research2NumStr(tabsBefore), Research2NumStr(tabs9), Research2NumStr(tabs8));
		} else if (!t0) {
			out += "｜U2=fail（读 numTabs 失败）";
		} else if (!c9) {
			out += "｜U2=fail（构造 9 项数组 / 调用 SetTabsData 失败）";
		} else if (!t9 || tabs9 != tabsBefore + 1) {
			out += std::format("｜U2=fail（9 项后 numTabs={}，期望 {}）",
				Research2NumStr(tabs9), Research2NumStr(tabsBefore + 1));
		} else if (!c8) {
			out += "｜U2=fail（恢复 8 项失败）";
		} else {
			out += std::format("｜U2=fail（恢复后 numTabs={}，期望 {}）",
				Research2NumStr(tabs8), Research2NumStr(tabsBefore));
		}

		return out;
	}

	// ======================================================================
	// ★★★ 第 120 轮（P2 · 原版 SWF 完整 PoC · docs/15 九·补三/九·补四）：
	//   `ui.research3` —— 「无 SWF 覆盖」目标形态的完整链路验证（跑在**原版**
	//   missionmenu.swf 上；我们的 SWF 覆盖被临时禁用）。
	//
	//   与前两代的关系：
	//     · 第 117 轮（`ui.research`）：U0/U1/U2/U3 能力边界；
	//     · 第 119 轮（`ui.research2` / P1.5）：在**我们的** SWF 上验证「绕过 U1」
	//       （拦截 + filterMask 哨兵写 + SetTabsData 补测）；
	//     · 本轮（`ui.research3` / P2）：把三段拼成**原版环境**下的完整链路，且补上
	//       最后一块未验证能力 —— **列表数据注入**（`InitializeEntries`）。
	//
	//   判据链（一次执行；原版预期值随行输出）：
	//     R1 环境=(numTabs 7,entryCount 206,mask 0xFFFFFFFF)    ← 原版 tab 数 = 7
	//     R3 扩tab=ok（7→8）                                   ← SetTabsData 7→8
	//     R4 切3=ok（mask 0xFFFFFFFF→0x00000008）              ← 原版执行（对照）
	//     R5 切7=ok（拦截 1 次,mask→0x20000000）               ← 哨兵存活 = 拦截 + 写双成立
	//     R6 切0=ok（mask→0xFFFFFFFF）                         ← 放行（不越权）
	//     R7 清理=ok
	//     R9 注入=ok（entryCount 206→3）                       ← InitializeEntries 生效
	//
	//   ★ R5 为什么是「第 8 个 tab 必须拦截」的硬证据：原版 SWF 的 `FilterInfoA` 只有
	//     7 项，原版 `onFilterChanged`（priority=0）会读 `FilterInfoA[7].flag` ——
	//     undefined.flag ⇒ TypeError。我们 priority=100 + stopImmediatePropagation
	//     拦住它，自己设 mask（产品形态下这就是「切到我们的 tab」）。
	//   ★ 副作用（tab 假数据 / 列表被替换 / filterMask）随 `menu.close` 清理
	//     （第 27/50 轮定案）—— 本探针不做还原。
	// ======================================================================
	namespace
	{
		constexpr std::uint32_t kResearch3SentinelMask = 1u << 29;      // 哨兵（同 P1.5：绝不为任何 tab 的 flag）
		constexpr std::uint32_t kResearch3NewTabFlag = 1u << 6;         // = 1<<AVAILABLE_QUEST_TYPE（产品值 64）
		constexpr std::uint32_t kResearch3InjectCount = 3;              // 列表注入条数
		constexpr std::uint32_t kResearch3InjectType = 6;               // 注入条目的 iType（AVAILABLE）
		constexpr std::uint32_t kResearch3InjectBaseUID = 0x12340000u;  // 注入条目 uID 基线（不与真任务撞号）
		constexpr const char*   kResearch3EventName = "BSTabbedSelection::selectionChange";
		constexpr const char*   kResearch3NewTabText = "SAQ-PoC";       // 新 tab 文本（ASCII，避免编码不确定性）
		constexpr std::uint32_t kResearch3InterceptPriority = 100;      // 原版 onFilterChanged 是 0

		// 拦截 handler（同 P1.5 的 Research2EventHandler，差别 = 拦截下标由构造参数给
		//   —— P2 的新 tab 下标 = 扩 tab 前的 numTabs，原版是 7）。
		//   生命周期同 P1.5：堆分配（RefCountBase 初始 0；事件系统 AddRef，remove 后
		//   Release → 0 → delete）⇒ **remove 之后绝不能再解引用**（统计必须先抄走）。
		class Research3EventHandler : public RE::Scaleform::GFx::FunctionHandler
		{
		public:
			Research3EventHandler(RE::Scaleform::GFx::Value a_missionsList, int a_interceptIndex) :
				m_missionsList(a_missionsList),  // 拷贝（AddRef）—— 只在本次菜单生命周期内用
				m_interceptIndex(a_interceptIndex)
			{}

			void Call(const Params& a_params) override
			{
				int idx = -1;
				if (a_params.argCount >= 1 && a_params.args) {
					RE::Scaleform::GFx::Value iv;
					double                  d = -1.0;
					if (a_params.args[0].GetMember("iSelectedIndex", &iv) && SafeReadValueNumber(iv, d)) {
						idx = static_cast<int>(d);
					}
				}
				const int n = ++s_calls;
				s_lastIndex = idx;
				bool stopped = false;
				if (idx == m_interceptIndex && a_params.argCount >= 1 && a_params.args) {
					// 拦住原版 onFilterChanged（priority=0）—— 不拦的话它随后执行
					//   `filterMask = FilterInfoA[7].flag`（原版 7 项 ⇒ 越界 TypeError）。
					RE::Scaleform::GFx::Value ret;
					(void)SafeValueInvoke(&a_params.args[0], "stopImmediatePropagation", &ret, nullptr, 0);
					RE::Scaleform::GFx::Value sentinel(static_cast<std::uint32_t>(kResearch3SentinelMask));
					const bool wrote = SafeValueSetMember(&m_missionsList, "filterMask", sentinel);
					// 读回验证（不能只看 SetMember 返回值）
					RE::Scaleform::GFx::Value back;
					double                  backNum = -1.0;
					const bool readBack = SafeValueGetMember(&m_missionsList, "filterMask", &back) &&
						SafeReadValueNumber(back, backNum);
					stopped = wrote && readBack &&
						static_cast<std::uint32_t>(backNum) == kResearch3SentinelMask;
					if (stopped) {
						++s_blocks;
					}
				}
				s_lastStopped = stopped;
				REX::INFO("界面研究探针3：事件回调（第 {} 次 idx={} 拦截={}）", n, idx, stopped ? "是" : "否");
			}

			static std::atomic<int>  s_calls;
			static std::atomic<int>  s_blocks;
			static std::atomic<int>  s_lastIndex;
			static std::atomic<bool> s_lastStopped;

		private:
			RE::Scaleform::GFx::Value m_missionsList;
			int                      m_interceptIndex{ -1 };
		};
		std::atomic<int>  Research3EventHandler::s_calls{ 0 };
		std::atomic<int>  Research3EventHandler::s_blocks{ 0 };
		std::atomic<int>  Research3EventHandler::s_lastIndex{ -1 };
		std::atomic<bool> Research3EventHandler::s_lastStopped{ false };
	}

	std::string ResearchGfxInjection3()
	{
		std::string detail;
		if (!EnsureResolved(detail)) {
			return "桥没通（" + EscapeForLog(detail, 200) + "）";
		}
		auto& bridge = Cached();
		auto* root = reinterpret_cast<RE::Scaleform::GFx::ASMovieRootBase*>(bridge.asRoot);
		if (!root) {
			return "ASMovieRoot 指针为空";
		}

		std::string out;

		RE::Scaleform::GFx::Value menu;
		const bool menuOk = SafeGetVariable(root, "_root.Menu_mc", &menu) && menu.IsObject();
		if (!menuOk) {
			return "Menu_mc=fail（原版 SWF 的 root 实例名对不上？后面全部依赖它）";
		}
		out += "Menu_mc=ok";

		RE::Scaleform::GFx::Value tabSel;
		RE::Scaleform::GFx::Value list;
		const bool tabSelOk = SafeValueGetMember(&menu, "TabbedFilterSelection_mc", &tabSel) && tabSel.IsObject();
		const bool listOk = SafeValueGetMember(&menu, "MissionsList_mc", &list) && list.IsObject();
		if (!tabSelOk || !listOk) {
			return out + std::format("｜TabSel={} MissionsList={}（缺一个就做不下去）",
				tabSelOk ? "ok" : "fail", listOk ? "ok" : "fail");
		}

		auto readNum = [](RE::Scaleform::GFx::Value& a_obj, const char* a_name, double& a_out) -> bool {
			RE::Scaleform::GFx::Value v;
			return SafeValueGetMember(&a_obj, a_name, &v) && SafeReadValueNumber(v, a_out);
		};

		// ---- R1：环境（原版预期：numTabs=7、mask=$ALL=0xFFFFFFFF）----
		double     tabs0 = -1.0, entries0 = -1.0, mask0 = -1.0;
		const bool envOk = readNum(tabSel, "numTabs", tabs0) && readNum(list, "entryCount", entries0) &&
			readNum(list, "filterMask", mask0);
		if (!envOk) {
			return out + "｜环境=读失败（numTabs / entryCount / filterMask 三取一失败）";
		}
		out += std::format("｜环境=(numTabs {},entryCount {},mask {})",
			Research2NumStr(tabs0), Research2NumStr(entries0), Research2MaskHex(mask0));

		// 新 tab 的下标 = 扩 tab 前的 tab 数（追加在末尾；原版 = 7）
		const int interceptIndex = static_cast<int>(tabs0);

		// ---- R2：挂拦截监听（priority=100；原版 onFilterChanged 是 0）----
		auto* handler = new Research3EventHandler(list, interceptIndex);
		RE::Scaleform::GFx::Value fn;
		if (!(VtableSlotInModule(root, kSlotAsRootCreateFunction) &&
				SafeCreateFunction(root, &fn, handler, nullptr))) {
			return out + "｜事件=注册失败（CreateFunction）";
		}
		RE::Scaleform::GFx::Value evTitle;
		if (!SafeCreateString(root, &evTitle, kResearch3EventName)) {
			return out + "｜事件=注册失败（事件名编码失败）";
		}
		{
			RE::Scaleform::GFx::Value args[5];
			args[0] = evTitle;
			args[1] = fn;
			args[2] = false;
			args[3] = static_cast<std::uint32_t>(kResearch3InterceptPriority);
			args[4] = false;
			RE::Scaleform::GFx::Value ret;
			if (!SafeValueInvoke(&tabSel, "addEventListener", &ret, args, 5)) {
				return out + "｜事件=注册失败（addEventListener）";
			}
		}

		// 原版 public 入口（内部 SetSelectedIndex → dispatchEvent）；越界会被静默拒绝
		//   ⇒ 所以「切新 tab」必须放在「扩 tab」之后。
		auto switchTab = [&tabSel](std::uint32_t a_idx) -> bool {
			RE::Scaleform::GFx::Value arg(static_cast<std::uint32_t>(a_idx));
			RE::Scaleform::GFx::Value ret;
			return SafeValueInvoke(&tabSel, "SetSelectedCategoryIndex", &ret, &arg, 1);
		};
		auto readMask = [&list, &readNum](double& a_out) -> bool { return readNum(list, "filterMask", a_out); };

		// ---- R3：扩 tab（构造 N0+1 项 → SetTabsData → numTabs 读回）----
		//   前 N0 项 = P1.5 风格假数据（text "$SAQ-keep<i>"）；末项 = 我们的新 tab
		//   （text "SAQ-PoC"、flag=1<<6 —— 正是产品形态的那一项）。
		auto buildTabs = [&](std::uint32_t a_count, const char* a_tag) -> bool {
			RE::Scaleform::GFx::Value arr;
			if (!(VtableSlotInModule(root, kSlotAsRootCreateArray) && SafeCreateArray(root, &arr))) {
				return false;
			}
			for (std::uint32_t i = 0; i < a_count; ++i) {
				RE::Scaleform::GFx::Value item;
				if (!SafeCreateObject(root, &item)) {
					return false;
				}
				const bool last = (i + 1 == a_count);
				RE::Scaleform::GFx::Value t;
				const std::string text = last ? std::string{ kResearch3NewTabText } :
					std::format("${}{}", a_tag, i);
				if (SafeCreateString(root, &t, text.c_str())) {
					(void)SafeValueSetMember(&item, "text", t);
				}
				RE::Scaleform::GFx::Value f(static_cast<std::uint32_t>(
					last ? kResearch3NewTabFlag : (i == 0 ? 0xFFFFFFFFu : (1u << (i % 7)))));
				(void)SafeValueSetMember(&item, "flag", f);
				if (!SafeValuePushBack(&arr, item)) {
					return false;
				}
			}
			RE::Scaleform::GFx::Value ret;
			return SafeValueInvoke(&tabSel, "SetTabsData", &ret, &arr, 1);
		};
		double     tabs1 = -1.0;
		const bool c8 = buildTabs(static_cast<std::uint32_t>(tabs0) + 1, "SAQ-keep");
		const bool t1 = c8 && readNum(tabSel, "numTabs", tabs1);
		const bool passExpand = c8 && t1 && tabs1 == tabs0 + 1;
		out += std::format("｜扩tab={}（{}→{}）", passExpand ? "ok" : "fail",
			Research2NumStr(tabs0), Research2NumStr(tabs1));

		// ---- R4/R5/R6：切 3（对照）→ 切 N0（拦截）→ 切 0（放行）----
		double     maskA = -1.0, maskB = -1.0, maskC = -1.0;
		const bool s3 = switchTab(3);
		const bool rA = readMask(maskA);
		const bool sN = passExpand && switchTab(static_cast<std::uint32_t>(interceptIndex));
		const bool rB = readMask(maskB);
		const bool s0 = switchTab(0);
		const bool rC = readMask(maskC);
		// 统计先抄走（removeEventListener 之后 handler 可能被 delete，绝不再解引用）
		const int calls = Research3EventHandler::s_calls.load();
		const int blocks = Research3EventHandler::s_blocks.load();
		const int lastIdx = Research3EventHandler::s_lastIndex.load();

		// 判据：切 3 = mask 变化且非哨兵；切 N0 = 拦截计数 +1 + mask == 哨兵
		//   （原版若没被拦住会先抛 TypeError，mask 保持前值 ⇒ 哨兵不存活）；
		//   切 0 = 回到非哨兵且 != 切 N0 后的值。
		const bool pass3 = s3 && rA && maskA != mask0 &&
			maskA != static_cast<double>(kResearch3SentinelMask);
		const bool passN = sN && rB && blocks >= 1 &&
			maskB == static_cast<double>(kResearch3SentinelMask);
		const bool pass0 = s0 && rC && maskC != static_cast<double>(kResearch3SentinelMask) && maskC != maskB;
		out += std::format("｜切3={}（mask {}→{}）", pass3 ? "ok" : "fail",
			Research2MaskHex(mask0), Research2MaskHex(maskA));
		out += std::format("｜切{}={}（拦截 {} 次,mask→{}）", interceptIndex, passN ? "ok" : "fail",
			blocks, Research2MaskHex(maskB));
		out += std::format("｜切0={}（mask→{}）", pass0 ? "ok" : "fail", Research2MaskHex(maskC));
		out += std::format("｜回调={} 次（末次 idx={}）", calls, lastIdx);

		// ---- R7：清理监听（remove 之后 handler 生命周期归 GFx；不再触碰）----
		bool removed = false;
		{
			RE::Scaleform::GFx::Value remArgs[2];
			remArgs[0] = evTitle;
			remArgs[1] = fn;
			RE::Scaleform::GFx::Value ret;
			removed = SafeValueInvoke(&tabSel, "removeEventListener", &ret, remArgs, 2);
		}
		out += std::format("｜清理={}", removed ? "ok" : "fail");

		// ---- R8：自设 filterMask = 1<<6（模拟产品「切到我们的 tab」后的状态）----
		{
			RE::Scaleform::GFx::Value m(static_cast<std::uint32_t>(kResearch3NewTabFlag));
			(void)SafeValueSetMember(&list, "filterMask", m);
		}

		// ---- R9：列表数据注入（构造条目数组 → InitializeEntries → entryCount 读回）----
		//   条目字段 = 原版 QuestData 的最小集 + **过原版两道门的必需字段**：
		//   ① `IsRootEntry` = `MissionsListEntry.IsMission(param1)`
		//      = `param1.hasOwnProperty("aObjectives")`（原版 FilterRootEntries 的第一道
		//      门 —— 缺它整批被过滤：第 121 轮 P2 首跑实测 `注入=fail（entryCount 1→0）`，
		//      真因就是初版注入条目没带 aObjectives；我们 SWF 版的产品条目本来就带，
		//      靠 `bSaqAvailable` 分支放行，原版没有该分支 ⇒ 注入形态必须在字段上模拟
		//      mission 条目）；
		//   ② `EntryFilterCompare_Impl` = `(filterMask & 1 << iType) != 0`
		//      ⇒ iType=6 + mask=1<<6 通过（R8 已设 mask）。
		//   其余为渲染路径的防御字段（bActive / iRemainingTime —— 见 buildEntries 内注释）。
		auto buildEntries = [&](std::uint32_t a_count) -> bool {
			RE::Scaleform::GFx::Value arr;
			if (!(VtableSlotInModule(root, kSlotAsRootCreateArray) && SafeCreateArray(root, &arr))) {
				return false;
			}
			for (std::uint32_t i = 0; i < a_count; ++i) {
				RE::Scaleform::GFx::Value item;
				if (!SafeCreateObject(root, &item)) {
					return false;
				}
				RE::Scaleform::GFx::Value uid(static_cast<std::uint32_t>(kResearch3InjectBaseUID + i));
				(void)SafeValueSetMember(&item, "uID", uid);
				RE::Scaleform::GFx::Value inst(static_cast<std::uint32_t>(kResearch3InjectBaseUID + i));
				(void)SafeValueSetMember(&item, "uInstanceID", inst);
				RE::Scaleform::GFx::Value type(static_cast<std::int32_t>(kResearch3InjectType));
				(void)SafeValueSetMember(&item, "iType", type);
				RE::Scaleform::GFx::Value fac(static_cast<std::int32_t>(-1));
				(void)SafeValueSetMember(&item, "iFaction", fac);
				RE::Scaleform::GFx::Value bFalse(false);
				(void)SafeValueSetMember(&item, "bComplete", bFalse);
				(void)SafeValueSetMember(&item, "bFailed", bFalse);
				// ★★★ 第 121 轮实机判读的修复（P2 首跑 `注入=fail（entryCount 1→0）`）：
				//   原版 `FilterRootEntries` 的第一道门 = `IsRootEntry` =
				//   `MissionsListEntry.IsMission(param1)` = `param1.hasOwnProperty("aObjectives")`
				//   —— 没带 aObjectives 的条目会被整批丢掉（rawEntries 收下了，entryList 里
				//   一条都不留 ⇒ entryCount 0）。原版没有我们 SWF 的 `bSaqAvailable` 分支，
				//   所以运行时注入必须把条目做成「像原版 mission 条目」：空 aObjectives 数组
				//   即可（`GetChildrenOfEntry` 返回空数组 ⇒ 行照常渲染、展开无子项）。
				RE::Scaleform::GFx::Value objs;
				if (VtableSlotInModule(root, kSlotAsRootCreateArray) && SafeCreateArray(root, &objs)) {
					(void)SafeValueSetMember(&item, "aObjectives", objs);
				}
				// 渲染路径防御：`SetMissionTracked` 读 bActive（不设走 Inactive 分支，
				//   显式给 false 更可控）；`UpdateTimeRemainingText(iRemainingTime, …)`
				//   在 `iRemainingTime < 0` 时隐藏时间标签 —— 不设会走
				//   `GetQuestTimeRemainingString(undefined)` 那条渲染路径。
				RE::Scaleform::GFx::Value fActive(false);
				(void)SafeValueSetMember(&item, "bActive", fActive);
				RE::Scaleform::GFx::Value remain(static_cast<std::int32_t>(-1));
				(void)SafeValueSetMember(&item, "iRemainingTime", remain);
				RE::Scaleform::GFx::Value name;
				if (SafeCreateString(root, &name, std::format("SAQ-PoC-Item {}", i).c_str())) {
					(void)SafeValueSetMember(&item, "sName", name);
				}
				if (!SafeValuePushBack(&arr, item)) {
					return false;
				}
			}
			RE::Scaleform::GFx::Value ret;
			return SafeValueInvoke(&list, "InitializeEntries", &ret, &arr, 1);
		};
		double     entries1 = -1.0;
		const bool inj = buildEntries(kResearch3InjectCount) && readNum(list, "entryCount", entries1);
		const bool passInject = inj && entries1 == static_cast<double>(kResearch3InjectCount);
		if (passInject) {
			out += std::format("｜注入=ok（entryCount {}→{}）",
				Research2NumStr(entries0), Research2NumStr(entries1));
		} else if (!inj) {
			out += "｜注入=fail（构造条目数组 / 调用 InitializeEntries / 读 entryCount 失败）";
		} else {
			out += std::format("｜注入=fail（entryCount {}→{}，期望 {}）",
				Research2NumStr(entries0), Research2NumStr(entries1), Research2NumStr(kResearch3InjectCount));
		}

		return out;
	}

	// ======================================================================
	// ★★★ 第 130 轮（功能迁移探针 v4 / U5~U10 · docs/15 十一）：`ui.research4` 系列
	//
	//   第十一节评估把「无 SWF 覆盖」产品化的剩余未知点收敛成 5 项。本探针在
	//   **原版 SWF**（P2 态）上把它们一次问清（每项「调用 → 读回验证」，判据进
	//   一行产品日志 —— 红线六）：
	//
	//     U6 引擎条目直读：`MissionsList_mc.GetDataForEntry(i)` / `selectedEntry`
	//        （原版 public）—— 「切走我们 tab 时恢复原版列表」与「选中项是不是
	//        我们的」两个判据都靠它（原「订阅 QuestData 事件」不再是必需）。
	//     U8 语言判定 + 渲染文本：语言 = **引擎任务名**里的 CJK 统计（与 SWF 版
	//        SaqNameVerdict 同源；注入形态没有 AS3 侧任务名可看）；渲染文本 =
	//        读 clip 的 TextField（验收手段：描述/名字真的显示了）。
	//     U10 类通道：`loaderInfo.applicationDomain.getDefinition("…BSUIDataManager")`
	//        + 静态调用（`hasEventListener` 只读）+ `Subscribe("QuestData", C++ 函数)`
	//        —— 通了就能用「订阅引擎推送」替代 watchdog 轮询，并可用
	//        `dispatchCustomEvent` 实现「委托原版行为」。
	//     U5 按键接管（三条路，一次试完）：
	//        ① 读 `ButtonBar_mc.<Btn>_mc.Data` —— 原版 `MinimalButton.Data` 是
	//           **protected** ⇒ 与 U1（private）同类边界，预期读不到；
	//        ② `CreateObject` 带**类名**造真 AS3 实例（`UserEventData` → 事件数组
	//           `[ud]` → `UserEventManager` → `ButtonBaseData`）—— 这是 GFx 里唯一
	//           能拿到「真 ButtonData 实例」的办法；★ 第 131 轮实机判读修的缺陷：
	//           `ButtonBaseData` 的 param2 **只接受 UserEventData 或 Array**（原版
	//           正典写法 = `new ButtonBaseData("$REJECT",[new UserEventData("R3",fn)],…)`）
	//           —— 旧版传 UserEventManager 实例被 ctor 忽略 ⇒ `UserEvents=null` ⇒
	//           `HandleUserEvent` 空引用；现在改传数组 + **读回 `data.UserEvents` 的
	//           `NumUserEvents`** 作接线证据；
	//        ③ `SetButtonData` 换到按钮上 + public 的
	//           `MinimalButton.HandleUserEvent("R3",false,false)` **程序化触发按键
	//           路径** ⇒ 我们的 C++ `funcCallback` 被调用 = **按键可接管**。
	//           （接管不了也有 fallback：父条目 Enter = 引导，docs/15 11.4-⑥）
	//        为什么拿 **REJECT（R3）** 当靶子：它平时不可见（`bVisible=false`），
	//        探测期间被换 Data 对玩家无观感影响；`Enabled` 初值 = true，换成
	//        `bEnabled=false` 后读回 false ⇒ **副证「实例被接受并被 AS3 侧读取」**。
	//     U9 关闭原语：public 的 `MissionMenu.ProcessUserEvent("SAQ_Research",false)`
	//        判据 = **可调用 + 无副作用（菜单仍在）**；★ 第 131 轮修正：原版末尾会把
	//        返回值**覆盖**为 ButtonBar / TabbedFilterSelection 的结果 —— 未知事件
	//        返回 true 属正常（旧判据「必须返回 false」是错的），返回值只作信息记录；
	//        真关菜单 = 传 `"ReturnToStarMap"` / `"Missions"`（留到 P4 用驱动器验证）。
	//     另加：`bCanShowOnMap` 字段 ⇒ SET COURSE 按钮 `Enabled` 的**数据驱动**验证
	//        （11.4-⑦「不可导航 ⇒ 置灰」：条目 0 给 false、条目 1 给 true，选中后
	//        读按钮 Enabled 必须 0 / 1）。
	//
	//   为什么拆两段（4 / 4b）：U7（就地刷新）是**渲染层**证据 —— clip 的
	//   `itemIndex` 由 `BSScrollingContainer.Update` 在**帧推进**时写，注入与读回
	//   之间必须隔一帧（P2 计划在两步之间插 `wait 1200`）；其余各项都是对象/数据
	//   层，同一次调用内完成。
	//   副作用（注入条目 / mask / REJECT 的 Data）随 `menu.close`（Movie 销毁）
	//   清理 —— 第 27/50 轮定案。
	// ======================================================================
	namespace
	{
		constexpr std::uint32_t kResearch4InjectCount = 2;                 // 注入条数（0=未导航 / 1=可导航）
		constexpr std::uint32_t kResearch4InjectType = 6;                  // = AVAILABLE_QUEST_TYPE（掩码 1<<6）
		constexpr std::uint32_t kResearch4InjectBaseUID = 0x56780000u;     // 探针 uID 基线（不与真任务撞号）
		constexpr std::uint32_t kResearch4NewTabFlag = 1u << 6;            // 我们 tab 的掩码（与探针 v3 同值）
		constexpr const char*   kResearch4RejectKey = "R3";                // REJECT 按钮的 UserEvent 名（原版 PopulateButtonBar）
		constexpr const char*   kResearch4InertCode = "SAQ_Research4";     // 惰性事件名（没人监听；防引擎收到未知 questID）
		constexpr const char*   kResearch4QuestDataChannel = "QuestData";  // 引擎任务数据通道（原版 Subscribe 用的同一个）
		constexpr const char*   kResearch4BsUiDataManager = "Shared.AS3.Data.BSUIDataManager";

		// AS3 类名候选（CreateObject 的 className：先全名、再短名、再 `::` 分隔写法 ——
		//   哪种有效本身也是本轮要测的；命中率最高的写法会写进 docs）。
		constexpr std::size_t kResearch4ClassNameCount = 3;
		const char* const kResearch4UedNames[] = {
			"Shared.Components.ButtonControls.ButtonData.UserEventData",
			"UserEventData",
			"Shared.Components.ButtonControls.ButtonData::UserEventData"
		};
		const char* const kResearch4UemNames[] = {
			"Shared.Components.ButtonControls.ButtonData.UserEventManager",
			"UserEventManager",
			"Shared.Components.ButtonControls.ButtonData::UserEventManager"
		};
		const char* const kResearch4BbdNames[] = {
			"Shared.Components.ButtonControls.ButtonData.ButtonBaseData",
			"ButtonBaseData",
			"Shared.Components.ButtonControls.ButtonData::ButtonBaseData"
		};

		bool SafeReadValueBool(const RE::Scaleform::GFx::Value& a_value, bool& a_out)
		{
			__try {
				if (a_value.IsBoolean()) {
					a_out = a_value.GetBoolean();
					return true;
				}
				return false;
			} __except (EXCEPTION_EXECUTE_HANDLER) {
				return false;
			}
		}

		// ★★★ 第 130 轮新能力：`CreateObject(Value*, className, args, numArgs)` ——
		//   带类名就直接造 AS3 类实例（本轮才知道 commonlibsf 的 0x2E 槽有 className
		//   参数）。逐个候选名试，命中即返回（失败不抛 C++ 异常；AS3 侧的错误由
		//   GFx 自己记日志）。
		bool SafeCreateObjectOfClass(RE::Scaleform::GFx::ASMovieRootBase* a_root,
			RE::Scaleform::GFx::Value* a_out, const char* const* a_names, std::size_t a_nameCount,
			const RE::Scaleform::GFx::Value* a_args, std::uint32_t a_numArgs)
		{
			if (!VtableSlotInModule(a_root, kSlotAsRootCreateObject)) {
				return false;
			}
			for (std::size_t i = 0; i < a_nameCount; ++i) {
				__try {
					a_root->CreateObject(a_out, a_names[i], a_args, a_numArgs);
				} __except (EXCEPTION_EXECUTE_HANDLER) {
					continue;
				}
				if (a_out->IsObject()) {
					return true;
				}
			}
			return false;
		}

		// 日志用：截断长文本（超出加省略号）。
		std::string ClipLogText(const std::string& a_text, std::size_t a_max)
		{
			return a_text.size() <= a_max ? a_text : a_text.substr(0, a_max) + "…";
		}

		// U8a：UTF-8 里的 CJK 统计（3 字节序列、前导字节 E4~E9 = U+4000~U+9FFF）。
		//   判据与 SWF 版 `SaqNameVerdict` 同源：**引擎推来的任务名**是本地化的。
		std::size_t CountCjkUtf8(const std::string& a_text)
		{
			std::size_t n = 0;
			for (std::size_t i = 0; i + 2 < a_text.size(); ++i) {
				const auto c = static_cast<unsigned char>(a_text[i]);
				if (c >= 0xE4 && c <= 0xE9) {
					++n;
					i += 2;
				}
			}
			return n;
		}

		// U5：被换上去的 `funcCallback`（按键路径真的走到这里 = 接管成立）。
		class Research4Handler : public RE::Scaleform::GFx::FunctionHandler
		{
		public:
			void Call(const Params& a_params) override
			{
				++s_calls;
				REX::INFO("界面研究探针4：接管回调收到（第 {} 次，argCount={}）", s_calls.load(), a_params.argCount);
			}
			static std::atomic<int> s_calls;
		};
		std::atomic<int> Research4Handler::s_calls{ 0 };

		// U10：`BSUIDataManager.Subscribe("QuestData", …)` 的回调（引擎推送计数 ——
		//   第二段读回；本会话没有新推送时为 0，属正常）。
		class Research4QuestDataHandler : public RE::Scaleform::GFx::FunctionHandler
		{
		public:
			void Call(const Params& a_params) override
			{
				(void)a_params;
				++s_calls;
				REX::INFO("界面研究探针4：QuestData 订阅回调收到（第 {} 次）", s_calls.load());
			}
			static std::atomic<int> s_calls;
		};
		std::atomic<int> Research4QuestDataHandler::s_calls{ 0 };
	}

	std::string ResearchGfxInjection4()
	{
		std::string detail;
		if (!EnsureResolved(detail)) {
			return "桥没通（" + EscapeForLog(detail, 200) + "）";
		}
		auto& bridge = Cached();
		auto* root = reinterpret_cast<RE::Scaleform::GFx::ASMovieRootBase*>(bridge.asRoot);
		if (!root) {
			return "ASMovieRoot 指针为空";
		}

		std::string out;

		RE::Scaleform::GFx::Value menu;
		if (!(SafeGetVariable(root, "_root.Menu_mc", &menu) && menu.IsObject())) {
			return "Menu_mc=fail（路径取不到，后面全部依赖它）";
		}
		out += "Menu_mc=ok";

		RE::Scaleform::GFx::Value list;
		RE::Scaleform::GFx::Value buttonBar;
		const bool listOk = SafeValueGetMember(&menu, "MissionsList_mc", &list) && list.IsObject();
		const bool barOk = SafeValueGetMember(&menu, "ButtonBar_mc", &buttonBar) && buttonBar.IsObject();
		if (!listOk || !barOk) {
			return out + std::format("｜List={} ButtonBar={}（缺一个就做不下去）",
				listOk ? "ok" : "fail", barOk ? "ok" : "fail");
		}

		auto readNum = [](RE::Scaleform::GFx::Value& a_obj, const char* a_name, double& a_out) -> bool {
			RE::Scaleform::GFx::Value v;
			return SafeValueGetMember(&a_obj, a_name, &v) && SafeReadValueNumber(v, a_out);
		};
		auto readStr = [](RE::Scaleform::GFx::Value& a_obj, const char* a_name, std::string& a_out) -> bool {
			RE::Scaleform::GFx::Value v;
			char                    buf[256]{};
			if (!SafeValueGetMember(&a_obj, a_name, &v) || !SafeReadValueString(v, buf, sizeof(buf))) {
				return false;
			}
			a_out = buf;
			return true;
		};
		auto readBool = [](RE::Scaleform::GFx::Value& a_obj, const char* a_name, bool& a_out) -> bool {
			RE::Scaleform::GFx::Value v;
			return SafeValueGetMember(&a_obj, a_name, &v) && SafeReadValueBool(v, a_out);
		};
		// `GetDataForEntry(i)`（原版 public）—— U6 的读入口。
		auto getEntry = [&list](std::uint32_t a_index, RE::Scaleform::GFx::Value& a_out) -> bool {
			RE::Scaleform::GFx::Value arg(static_cast<std::int32_t>(a_index));
			RE::Scaleform::GFx::Value ret;
			if (!SafeValueInvoke(&list, "GetDataForEntry", &ret, &arg, 1) || !ret.IsObject()) {
				return false;
			}
			a_out = ret;
			return true;
		};
		auto readSelectedUID = [&list, &readNum](double& a_out) -> bool {
			RE::Scaleform::GFx::Value se;
			if (!SafeValueGetMember(&list, "selectedEntry", &se) || !se.IsObject()) {
				return false;
			}
			return readNum(se, "uID", a_out);
		};

		// ---- 环境 ----
		double entries0 = -1.0, mask0 = -1.0;
		(void)readNum(list, "entryCount", entries0);
		(void)readNum(list, "filterMask", mask0);
		out += std::format("｜环境=(entryCount {},mask {})", Research2NumStr(entries0), Research2MaskHex(mask0));

		// ---- U6：引擎条目直读（首条字段 + 选中项）----
		std::string sampleName;
		std::string firstNote = "-";
		bool        readOk = false;
		if (entries0 >= 1.0) {
			RE::Scaleform::GFx::Value e0;
			if (getEntry(0, e0)) {
				double      uid = -1.0, itype = -1.0;
				std::string nm;
				(void)readNum(e0, "uID", uid);
				(void)readNum(e0, "iType", itype);
				(void)readStr(e0, "sName", nm);
				sampleName = nm;
				int fields = 0;
				for (const char* f : { "uID", "sName", "iType", "iFaction", "aObjectives", "bActive", "bComplete", "iRemainingTime" }) {
					if (e0.HasMember(f)) {
						++fields;
					}
				}
				firstNote = std::format("0x{:08X}:类型{:.0f}:名={}:字段{}",
					static_cast<std::uint32_t>(static_cast<std::uint64_t>(uid)), itype, ClipLogText(nm, 20), fields);
				readOk = uid >= 0.0 && !nm.empty();
			}
		}
		std::string selNote = "无";
		{
			double suid = -1.0;
			if (readSelectedUID(suid)) {
				selNote = std::format("0x{:08X}", static_cast<std::uint32_t>(static_cast<std::uint64_t>(suid)));
			}
		}
		if (entries0 < 1.0) {
			out += "｜读条目=fail（entryCount 0，无样本）";
		} else {
			out += std::format("｜读条目={}（{:.0f} 条,首条 {}｜选中项={}）",
				readOk ? "ok" : "fail", entries0, firstNote, selNote);
		}

		// ---- U8a：语言判定（引擎任务名 = 本地化样本）----
		if (sampleName.empty()) {
			out += "｜语言=?（无样本）";
		} else {
			const std::size_t cjk = CountCjkUtf8(sampleName);
			if (cjk > 0) {
				out += std::format("｜语言=zh（中文样本 {} 字）", cjk);
			} else {
				out += "｜语言=en（无中文样本）";
			}
		}

		// ---- U10：类通道（applicationDomain.getDefinition → 静态方法 → 订阅）----
		std::string                 classNote = "fail（loaderInfo/applicationDomain 断链）";
		std::string                 staticNote = "未做";
		std::string                 subNote = "未做";
		bool                        classOk = false;
		RE::Scaleform::GFx::Value   classObj;
		{
			RE::Scaleform::GFx::Value loaderInfo, appDomain;
			if (SafeValueGetMember(&list, "loaderInfo", &loaderInfo) && loaderInfo.IsObject() &&
				SafeValueGetMember(&loaderInfo, "applicationDomain", &appDomain) && appDomain.IsObject()) {
				RE::Scaleform::GFx::Value nameVal;
				if (SafeCreateString(root, &nameVal, kResearch4BsUiDataManager)) {
					RE::Scaleform::GFx::Value args[1]{ nameVal };
					RE::Scaleform::GFx::Value def;
					if (SafeValueInvoke(&appDomain, "getDefinition", &def, args, 1) && def.IsObject()) {
						classObj = def;
						classOk = true;
						classNote = "ok（BSUIDataManager）";
					} else {
						classNote = "fail（getDefinition 失败）";
					}
				} else {
					classNote = "fail（类名编码失败）";
				}
			}
		}
		if (classOk) {
			RE::Scaleform::GFx::Value evName;
			if (SafeCreateString(root, &evName, kResearch4QuestDataChannel)) {
				RE::Scaleform::GFx::Value args[1]{ evName };
				RE::Scaleform::GFx::Value ret;
				bool                    has = false;
				if (SafeValueInvoke(&classObj, "hasEventListener", &ret, args, 1) && SafeReadValueBool(ret, has)) {
					staticNote = std::format("ok（hasEventListener={}）", has ? "true" : "false");
				} else {
					staticNote = "fail（静态方法不可调）";
				}
				RE::Scaleform::GFx::Value fn;
				if (VtableSlotInModule(root, kSlotAsRootCreateFunction) &&
					SafeCreateFunction(root, &fn, new Research4QuestDataHandler(), nullptr)) {
					RE::Scaleform::GFx::Value sargs[2]{ evName, fn };
					RE::Scaleform::GFx::Value sret;
					subNote = SafeValueInvoke(&classObj, "Subscribe", &sret, sargs, 2) ?
						"ok" : "fail（Subscribe 调用失败）";
				} else {
					subNote = "fail（CreateFunction 失败）";
				}
			} else {
				staticNote = "fail（事件名编码失败）";
			}
		}
		out += std::format("｜类通道={}｜静态={}｜订阅={}", classNote, staticNote, subNote);

		// ---- U5：按键接管（REJECT 按钮；三条路一次试完）----
		RE::Scaleform::GFx::Value reject;
		const bool               rejectOk = SafeValueGetMember(&buttonBar, "RejectButton_mc", &reject) && reject.IsObject();
		bool                     enBefore = false;
		const bool               enRead = rejectOk && readBool(reject, "Enabled", enBefore);
		bool                     dataReadable = false;
		if (rejectOk) {
			RE::Scaleform::GFx::Value d;
			dataReadable = reject.HasMember("Data") &&
				SafeValueGetMember(&reject, "Data", &d) && d.IsObject();
		}
		std::string dataNote = rejectOk ?
			(dataReadable ? "ok（protected 可读）" : "fail（Data 是 protected trait —— 与 U1 同类边界）") :
			"fail（RejectButton_mc 取不到）";
		std::string makeNote = "未做";
		std::string takeNote = "未试";
		if (rejectOk && enRead && VtableSlotInModule(root, kSlotAsRootCreateFunction)) {
			RE::Scaleform::GFx::Value ourFn;
			if (SafeCreateFunction(root, &ourFn, new Research4Handler(), nullptr)) {
				// ① UserEventData（真实例）：(sUserEvent, funcCallback, sCodeCallback, bEnabled)
				RE::Scaleform::GFx::Value ud;
				bool                    ok1 = false;
				{
					RE::Scaleform::GFx::Value key, code;
					if (SafeCreateString(root, &key, kResearch4RejectKey) &&
						SafeCreateString(root, &code, kResearch4InertCode)) {
						RE::Scaleform::GFx::Value args[4]{ key, ourFn, code, RE::Scaleform::GFx::Value(true) };
						ok1 = SafeCreateObjectOfClass(root, &ud, kResearch4UedNames,
							kResearch4ClassNameCount, args, 4);
					}
				}
				std::string udKey;
				if (ok1) {
					ok1 = readStr(ud, "sUserEvent", udKey) && udKey == kResearch4RejectKey;
				}
				// ② 事件数组 [ud]（★ 第 131 轮修正的关键）：原版 `ButtonBaseData` 的
				//   param2 **只接受 UserEventData 或 Array**（见 ButtonBaseData.as 的 ctor：
				//   其它类型走 `GlobalFunc.TraceWarning("aUserEvents is not a UserEventData
				//   or Array")` 并**忽略** ⇒ `UserEvents` 保持 null（ButtonData 默认值）⇒
				//   `HandleUserEvent` 里 `this.Data.UserEvents.CallForMatchingData` 空引用
				//   ⇒ 触发失败、回调 0 次）。原版正典写法 =
				//   `new ButtonBaseData("$REJECT",[new UserEventData("R3",fn)],…)`。
				RE::Scaleform::GFx::Value arr;
				bool                    arrOk = false;
				if (ok1) {
					arrOk = SafeCreateArray(root, &arr) && SafeValuePushBack(&arr, ud);
				}
				// ②b UserEventManager（真实例）：ctor 参数 = 事件数组；**读回 NumUserEvents=1**
				//   （光「造出来是个 object」不算接线成功 —— 第 131 轮的教训）。
				RE::Scaleform::GFx::Value uem;
				bool                    ok2 = false;
				double                  uemNum = -1.0;
				if (arrOk) {
					RE::Scaleform::GFx::Value args[1]{ arr };
					ok2 = SafeCreateObjectOfClass(root, &uem, kResearch4UemNames,
						kResearch4ClassNameCount, args, 1);
					if (ok2) {
						ok2 = readNum(uem, "NumUserEvents", uemNum) && uemNum == 1.0;
					}
				}
				// ③ ButtonBaseData（真实例）：("$REJECT", [ud], bEnabled=false, bVisible=false)
				//   —— bEnabled 给 false：SetButtonData 之后按钮 `Enabled` 由 true 变 false
				//   即是「实例被接受并被 AS3 侧读到」的副证。
				//   ★ 第 131 轮：param2 改传**数组**（旧版传 UserEventManager 实例 —— 被
				//   ctor 忽略 ⇒ 接管 fail 的探针缺陷），并**读回 `data.UserEvents`**
				//   作接线证据（防同类缺陷再犯；verify 特征串「接线 UserEvents=」）。
				RE::Scaleform::GFx::Value data;
				bool                    ok3 = false;
				double                  wireNum = -1.0;
				bool                    wireOk = false;
				if (ok2) {
					RE::Scaleform::GFx::Value t;
					if (SafeCreateString(root, &t, "$REJECT")) {
						RE::Scaleform::GFx::Value args[4]{ t, arr,
							RE::Scaleform::GFx::Value(false), RE::Scaleform::GFx::Value(false) };
						ok3 = SafeCreateObjectOfClass(root, &data, kResearch4BbdNames,
							kResearch4ClassNameCount, args, 4);
					}
					if (ok3) {
						RE::Scaleform::GFx::Value uev;
						wireOk = SafeValueGetMember(&data, "UserEvents", &uev) && uev.IsObject() &&
							readNum(uev, "NumUserEvents", wireNum) && wireNum == 1.0;
					}
				}
				if (ok1 && arrOk && ok2 && ok3 && wireOk) {
					makeNote = "ok（三级 + 接线 UserEvents=1）";
				} else {
					const std::string stage =
						!ok1 ? std::string{ "UserEventData" } :
						!arrOk ? std::string{ "事件数组" } :
						!ok2 ? std::format("UserEventManager（NumUserEvents={}）", Research2NumStr(uemNum)) :
						!ok3 ? std::string{ "ButtonBaseData" } :
						std::format("接线（UserEvents NumUserEvents={}）", Research2NumStr(wireNum));
					makeNote = std::format("fail（断在{}）", stage);
				}
				if (ok3) {
					RE::Scaleform::GFx::Value ret;
					const bool               setOk = SafeValueInvoke(&reject, "SetButtonData", &ret, &data, 1);
					bool                     enAfter = enBefore;
					const bool               enAfterOk = readBool(reject, "Enabled", enAfter);
					if (setOk && enAfterOk && enBefore && !enAfter) {
						// ④ 复原 `bEnabled=true` + RefreshButtonData（Data 已是真 ButtonData，
						//   `this.Data as ButtonData` 的类型转换安全）⇒ Enabled 回 true。
						RE::Scaleform::GFx::Value bTrue(true);
						(void)SafeValueSetMember(&data, "bEnabled", bTrue);
						RE::Scaleform::GFx::Value ret2;
						const bool               refreshed = SafeValueInvoke(&reject, "RefreshButtonData", &ret2, nullptr, 0);
						bool                     enNow = false;
						const bool               enNowOk = readBool(reject, "Enabled", enNow);
						// ⑤ 程序化触发按键路径（public `HandleUserEvent`；pressed=false ⇒
						//   走 CallForMatchingData → OnMouseClick → funcCallback）。
						const int                before = Research4Handler::s_calls.load();
						RE::Scaleform::GFx::Value key;
						bool                     trig = false;
						if (SafeCreateString(root, &key, kResearch4RejectKey)) {
							RE::Scaleform::GFx::Value args[3]{ key,
								RE::Scaleform::GFx::Value(false), RE::Scaleform::GFx::Value(false) };
							RE::Scaleform::GFx::Value tret;
							trig = SafeValueInvoke(&reject, "HandleUserEvent", &tret, args, 3);
						}
						const int calls = Research4Handler::s_calls.load() - before;
						takeNote = (refreshed && enNowOk && enNow && trig && calls == 1) ?
							"ok（回调收到 1 次 —— R 键可接管）" :
							std::format("fail（刷新={} 触发={} 回调={} 次 Enabled={}）",
								refreshed ? "ok" : "fail", trig ? "ok" : "fail", calls, enNow ? "1" : "0");
					} else {
						takeNote = std::format("fail（SetButtonData 未生效：Enabled {}→{} set={}）",
							enBefore ? "1" : "0", enAfter ? "1" : "0", setOk ? "ok" : "fail");
					}
				}
			} else {
				makeNote = "fail（CreateFunction 失败）";
			}
		} else if (!rejectOk) {
			makeNote = "fail（RejectButton_mc 取不到）";
		} else if (!enRead) {
			makeNote = "fail（Enabled 读不到）";
		} else {
			makeNote = "fail（CreateObject 槽不在）";
		}
		out += std::format("｜读Data={}｜造对象={}｜接管={}", dataNote, makeNote, takeNote);

		// ---- 注入（真实字段集）+ 选中 + 置灰（bCanShowOnMap 数据驱动）----
		{
			RE::Scaleform::GFx::Value m(static_cast<std::uint32_t>(kResearch4NewTabFlag));
			(void)SafeValueSetMember(&list, "filterMask", m);
		}
		auto buildEntries = [&](std::uint32_t a_count) -> bool {
			RE::Scaleform::GFx::Value arr;
			if (!(VtableSlotInModule(root, kSlotAsRootCreateArray) && SafeCreateArray(root, &arr))) {
				return false;
			}
			for (std::uint32_t i = 0; i < a_count; ++i) {
				RE::Scaleform::GFx::Value item;
				if (!SafeCreateObject(root, &item)) {
					return false;
				}
				const auto uid = static_cast<std::uint32_t>(kResearch4InjectBaseUID + i);
				(void)SafeValueSetMember(&item, "uID", RE::Scaleform::GFx::Value(uid));
				(void)SafeValueSetMember(&item, "uInstanceID", RE::Scaleform::GFx::Value(uid));
				(void)SafeValueSetMember(&item, "iType", RE::Scaleform::GFx::Value(static_cast<std::int32_t>(kResearch4InjectType)));
				(void)SafeValueSetMember(&item, "iFaction", RE::Scaleform::GFx::Value(static_cast<std::int32_t>(-1)));
				(void)SafeValueSetMember(&item, "bComplete", RE::Scaleform::GFx::Value(false));
				(void)SafeValueSetMember(&item, "bFailed", RE::Scaleform::GFx::Value(false));
				// 原版 `IsMission` = hasOwnProperty("aObjectives")（第 122 轮 P2 首跑的真因）——
				//   空数组即通过第一道门（`GetChildrenOfEntry` 返回空数组 ⇒ 行照常渲染）。
				RE::Scaleform::GFx::Value objs;
				if (VtableSlotInModule(root, kSlotAsRootCreateArray) && SafeCreateArray(root, &objs)) {
					(void)SafeValueSetMember(&item, "aObjectives", objs);
				}
				(void)SafeValueSetMember(&item, "bActive", RE::Scaleform::GFx::Value(false));
				(void)SafeValueSetMember(&item, "iRemainingTime", RE::Scaleform::GFx::Value(static_cast<std::int32_t>(-1)));
				RE::Scaleform::GFx::Value nm, desc;
				if (SafeCreateString(root, &nm, std::format("SAQ-Mig-{}", i).c_str())) {
					(void)SafeValueSetMember(&item, "sName", nm);
				}
				if (SafeCreateString(root, &desc, std::format("SAQ migration probe #{} — description comes from the sDescription field.", i).c_str())) {
					(void)SafeValueSetMember(&item, "sDescription", desc);
				}
				// 条目 0 = 不可导航（SET COURSE 必须置灰）/ 条目 1 = 可导航（必须亮）。
				(void)SafeValueSetMember(&item, "bCanShowOnMap", RE::Scaleform::GFx::Value(i == 1));
				if (!SafeValuePushBack(&arr, item)) {
					return false;
				}
			}
			RE::Scaleform::GFx::Value ret;
			return SafeValueInvoke(&list, "InitializeEntries", &ret, &arr, 1);
		};
		double     entries1 = -1.0;
		const bool inj = buildEntries(kResearch4InjectCount) && readNum(list, "entryCount", entries1);
		const bool passInject = inj && entries1 == static_cast<double>(kResearch4InjectCount);
		if (passInject) {
			out += std::format("｜注入=ok（entryCount {}→{}）",
				Research2NumStr(entries0), Research2NumStr(entries1));
		} else if (!inj) {
			out += "｜注入=fail（构造条目数组 / 调用 InitializeEntries / 读 entryCount 失败）";
		} else {
			out += std::format("｜注入=fail（entryCount {}→{}，期望 {}）",
				Research2NumStr(entries0), Research2NumStr(entries1), Research2NumStr(kResearch4InjectCount));
		}

		RE::Scaleform::GFx::Value plotBtn;
		const bool               plotOk = SafeValueGetMember(&buttonBar, "PlotToLocationButton_mc", &plotBtn) && plotBtn.IsObject();
		std::string              selOut = "fail（selectedIndex 写入 / selectedEntry 读回失败）";
		bool                     passSel = false;
		bool                     enNoNav = true, enNav = false;
		if (passInject) {
			auto selectIndex = [&list](std::uint32_t a_idx) -> bool {
				return SafeValueSetMember(&list, "selectedIndex", RE::Scaleform::GFx::Value(static_cast<std::int32_t>(a_idx)));
			};
			double     uid0 = -1.0, uid1 = -1.0;
			const bool s0 = selectIndex(0) && readSelectedUID(uid0);
			const bool b0 = plotOk && readBool(plotBtn, "Enabled", enNoNav);
			const bool s1 = selectIndex(1) && readSelectedUID(uid1);
			const bool b1 = plotOk && readBool(plotBtn, "Enabled", enNav);
			passSel = s0 && s1 && uid0 == static_cast<double>(kResearch4InjectBaseUID) &&
				uid1 == static_cast<double>(kResearch4InjectBaseUID + 1);
			selOut = passSel ? std::format("ok（0x{:08X}）", static_cast<std::uint32_t>(kResearch4InjectBaseUID + 1)) :
				std::format("fail（uid0={} uid1={}）",
					static_cast<std::int64_t>(uid0), static_cast<std::int64_t>(uid1));
			if (plotOk) {
				const bool passGrey = b0 && b1 && !enNoNav && enNav;
				out += std::format("｜选中={}｜置灰={}（不可导航={}，可导航={}）", selOut,
					passGrey ? "ok" : "fail", enNoNav ? "1" : "0", enNav ? "1" : "0");
			} else {
				out += std::format("｜选中={}｜置灰=fail（PlotToLocationButton_mc 取不到）", selOut);
			}
		} else {
			out += std::format("｜选中={}｜置灰=未做", selOut);
		}

		return out;
	}

	std::string ResearchGfxInjection4b()
	{
		std::string detail;
		if (!EnsureResolved(detail)) {
			return "桥没通（" + EscapeForLog(detail, 200) + "）";
		}
		auto& bridge = Cached();
		auto* root = reinterpret_cast<RE::Scaleform::GFx::ASMovieRootBase*>(bridge.asRoot);
		if (!root) {
			return "ASMovieRoot 指针为空";
		}

		std::string out;

		RE::Scaleform::GFx::Value menu;
		if (!(SafeGetVariable(root, "_root.Menu_mc", &menu) && menu.IsObject())) {
			return "Menu_mc=fail（路径取不到）";
		}
		out += "Menu_mc=ok";

		RE::Scaleform::GFx::Value list;
		const bool               listOk = SafeValueGetMember(&menu, "MissionsList_mc", &list) && list.IsObject();
		if (!listOk) {
			return out + "｜MissionsList_mc=fail";
		}

		auto readNum = [](RE::Scaleform::GFx::Value& a_obj, const char* a_name, double& a_out) -> bool {
			RE::Scaleform::GFx::Value v;
			return SafeValueGetMember(&a_obj, a_name, &v) && SafeReadValueNumber(v, a_out);
		};
		auto readStr = [](RE::Scaleform::GFx::Value& a_obj, const char* a_name, std::string& a_out) -> bool {
			RE::Scaleform::GFx::Value v;
			char                    buf[256]{};
			if (!SafeValueGetMember(&a_obj, a_name, &v) || !SafeReadValueString(v, buf, sizeof(buf))) {
				return false;
			}
			a_out = buf;
			return true;
		};

		double entries = -1.0, mask = -1.0;
		(void)readNum(list, "entryCount", entries);
		(void)readNum(list, "filterMask", mask);
		out += std::format("｜环境=(entryCount {},mask {})", Research2NumStr(entries), Research2MaskHex(mask));

		// ---- U7：就地刷新（第 0 行的 clip → 改条目 bActive → SetEntryText → 竖条帧名）----
		RE::Scaleform::GFx::Value clip;
		bool                     clipOk = false;
		double                   clips = -1.0;
		(void)readNum(list, "totalEntryClips", clips);
		for (std::uint32_t i = 0; i < 16 && clips > 0.0 &&
			i < static_cast<std::uint32_t>(clips); ++i) {
			RE::Scaleform::GFx::Value arg(static_cast<std::int32_t>(i));
			RE::Scaleform::GFx::Value c;
			if (!SafeValueInvoke(&list, "GetClipByIndex", &c, &arg, 1) || !c.IsObject()) {
				continue;
			}
			double idx = -2.0;
			if (readNum(c, "itemIndex", idx) && idx == 0.0) {
				clip = c;
				clipOk = true;
				break;
			}
		}
		if (!clipOk) {
			out += std::format("｜刷新=fail（行未渲染：{} 个 clip 里没有 itemIndex=0）｜文本=未做",
				Research2NumStr(clips));
		} else {
			auto readTrack = [&clip, &readStr](std::string& a_out) -> bool {
				RE::Scaleform::GFx::Value mv, ind;
				return SafeValueGetMember(&clip, "MissionVisuals_mc", &mv) && mv.IsObject() &&
					SafeValueGetMember(&mv, "TrackIndicator_mc", &ind) && ind.IsObject() &&
					readStr(ind, "currentLabel", a_out);
			};
			// `GetDataForEntry(0)` —— 拿回**原版列表里那条条目对象**（注入时构造的那个
			//   实例；改它的 bActive 再 SetEntryText = 产品形态的「就地刷新」）。
			auto getEntry = [&list](std::uint32_t a_index, RE::Scaleform::GFx::Value& a_out) -> bool {
				RE::Scaleform::GFx::Value arg(static_cast<std::int32_t>(a_index));
				RE::Scaleform::GFx::Value got;
				if (!SafeValueInvoke(&list, "GetDataForEntry", &got, &arg, 1) || !got.IsObject()) {
					return false;
				}
				a_out = got;
				return true;
			};
			std::string              l0, l1;
			RE::Scaleform::GFx::Value entry;
			const bool               haveEntry = getEntry(0, entry);
			const bool               read0 = readTrack(l0);
			const bool               wrote = haveEntry &&
				SafeValueSetMember(&entry, "bActive", RE::Scaleform::GFx::Value(true));
			RE::Scaleform::GFx::Value ret;
			const bool               refreshed = wrote && SafeValueInvoke(&clip, "SetEntryText", &ret, &entry, 1);
			const bool               read1 = refreshed && readTrack(l1);
			const bool               passRefresh = read0 && read1 && l0 == "Inactive" && l1 == "Active";
			out += std::format("｜刷新={}（竖条 {}→{}）", passRefresh ? "ok" : "fail",
				l0.empty() ? "?" : l0, l1.empty() ? "?" : l1);

			// ---- U8b：渲染文本（名字真的显示 = 验收手段）----
			std::string text;
			bool        textOk = false;
			{
				RE::Scaleform::GFx::Value mv, tf, tf2;
				if (SafeValueGetMember(&clip, "MissionVisuals_mc", &mv) && mv.IsObject() &&
					SafeValueGetMember(&mv, "TextField_tf", &tf) && tf.IsObject() &&
					SafeValueGetMember(&tf, "text_tf", &tf2) && tf2.IsObject()) {
					textOk = readStr(tf2, "text", text) && !text.empty();
				}
			}
			out += std::format("｜文本={}（{}）", textOk ? "ok" : "fail", ClipLogText(text, 16));
		}

		// ---- U9：关闭原语（★ 第 131 轮修正判据：**可调用 + 无副作用**；真关菜单留 P4）----
		//   旧判据「未知事件必须返回 false」不成立：原版 `MissionMenu.ProcessUserEvent`
		//   末尾把返回值**覆盖**为 `ButtonBar_mc.ProcessUserEvent` /
		//   `TabbedFilterSelection_mc.ProcessUserEvent` 的结果（见 MissionMenu.as）——
		//   未知事件下可能被某个按钮声称处理（返回 true），但**没有副作用**（菜单仍在）。
		//   真正的关菜单原语 = 传 `"ReturnToStarMap"`（OnCancelEvent）或 `"Missions"`
		//   （onCloseSubMenuToGame）—— 那会真关掉菜单（会打断人工观察窗口），
		//   按设计留到 P4 用驱动器验证。这里判 = 可调用 + 菜单仍在（无副作用）。
		{
			RE::Scaleform::GFx::Value evName;
			bool                     called = false;
			bool                     retIsBool = false;
			bool                     retBool = false;
			if (SafeCreateString(root, &evName, "SAQ_Research")) {
				RE::Scaleform::GFx::Value args[2]{ evName, RE::Scaleform::GFx::Value(false) };
				RE::Scaleform::GFx::Value ret;
				called = SafeValueInvoke(&menu, "ProcessUserEvent", &ret, args, 2);
				if (called) {
					retIsBool = SafeReadValueBool(ret, retBool);
				}
			}
			double     after = -1.0;
			const bool alive = readNum(list, "entryCount", after) && after == entries;
			const bool pass = called && alive;
			out += std::format("｜关菜单入口={}（可调用={}；菜单仍在={}；返回 {}，真关菜单留 P4）",
				pass ? "ok" : "fail", called ? "是" : "否", alive ? "是" : "否",
				!called ? "?" : (retIsBool ? (retBool ? "true" : "false") : "非布尔"));
		}

		// ---- U10 收口：QuestData 订阅回调计数（本会话没有新推送 ⇒ 0 属正常）----
		out += std::format("｜订阅回调={} 次", Research4QuestDataHandler::s_calls.load());

		return out;
	}
#endif
}
