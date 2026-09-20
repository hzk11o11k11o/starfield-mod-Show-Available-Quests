Scriptname SAQ_Main extends Quest

; ============================================================================
;  Starfield Show Available Quests - 主 Papyrus 脚本（代理引导任务）
;
;  绑定在 SAQ_ShowAvailableQuests.esm 的 SAQ_MainQuest 上（Start Game Enabled）。
;
;  ## 它干什么
;
;  玩家的「可接任务」tab 里选中一条任务、按下引导键之后：
;    DLL 侧  → 把引导目标的 FormID 写进 GLOB SAQ_GuideTargetRef，并把 SAQ_GuideState 清 0
;    本脚本  → 轮询看到 GuideState == 0，于是把目标引用 ForceRefTo 到本任务的别名
;              SAQ_GuideTarget 上、显示目标（objective 10）、把本任务设为「追踪中」
;    → 引擎于是画出任务标记（蓝点）+ 扫描仪路径线，指向那个引用
;
;  ## 为什么用代理任务
;
;  引擎只给「正在运行、且有已显示目标」的任务画标记；未接取的任务引擎不管。
;  代理任务 + 别名（ESM 里由 tools/esm/patch_saq_esm.py 挂上：
;  Reference Alias id=0「SAQ_GuideTarget」+ Objective 10「<Alias=SAQ_GuideTarget>」）
;  就是「借引擎的标记系统一用」。
;
;  ## 为什么用定时器轮询（而不是只靠菜单事件）
;
;  DLL 是在菜单**开着的时候**写 GLOB 的，脚本只知道菜单开关。如果玩家按完引导键
;  立刻关菜单，事件与写入之间就可能差一拍（错过一次要等下次开菜单才补上）。
;  Starfield 的 Papyrus 没有 RegisterForUpdate，但有 StartTimer/OnTimer，
;  0.5 秒一次的空判（GuideState != 0 直接返回）开销可以忽略，换来的是「菜单关着时
;  什么时候写都能收到」。
;
;  ★ 第 27 轮实测更正：菜单**开着**时 Papyrus 定时器不会触发（任务菜单暂停游戏 ⇒
;  StartTimer 不走）—— 三次会话的 Papyrus 日志里 `引导已应用` 都精确落在「菜单关闭」
;  那一刻，菜单开着 27~37 秒期间一次都没有。所以引导总是「关菜单时生效」，
;  与原版交互一致（HUD 也是关菜单才可见）。
;
;  ## 别名为什么用 GetAlias(0) 而不是脚本属性
;
;  VMAD 里的「别名属性」要写对 Object/Alias 联合体的字节格式，容易出错；
;  Quest.GetAlias(int) 原生函数直接按 id 取，零风险。
;
;  ## SAQ_GuideState 的取值（DLL 写 0/5/6/7，脚本写 1/2/3/4）
;
;    0 = 待处理（DLL 每次下新目标都会置 0）
;    1 = 已应用（ForceRefTo + 显示目标 + 设为追踪）
;    2 = 目标引用取不到（Game.GetForm 返回 None —— FormID 不对 / 表单没加载）
;    3 = 已清除（DLL 传 0：取消引导）
;    4 = 别名不存在（ESM 没打补丁 / 别名 id 变了）
;    5 = ★ 第 37 轮：待处理 + **应用完打开星图**（玩家在「可接任务」里按了
;        「设定航线（R）」）。界面侧（第 38 轮新协议）收到 C++ 成功回写后走原版
;        「退回游戏」路径把整个暂停菜单关掉，本脚本随即在「菜单关闭」事件里跑：
;        ① 照常应用引导；② 把「待打开星图」记进待办（StarMapPendingTicks）。
;        ★★ 第 44 轮：调用改由**轮询节拍**推进（见 ProcessStarMapPending）——
;        取引导目标的地点（GetCurrentLocation / GetEditorLocation），调用引擎原生的
;          Game.ShowGalaxyStarMapMenuAndPlotToLocation(地点)
;        打开星图并把航线画到那里（= 原版 SET COURSE 的同款能力）。
;        为什么必须这么绕：任务菜单开着时 Papyrus 定时器不走（第 27 轮实测定案），
;        脚本只能在菜单关闭时跑；而 DLL 直接调 Papyrus 原生函数要伪造 VM 栈帧，
;        风险远大于收益（详见 docs/05 第十一节）。
;    6/7 = ★ 第 40 轮：同 5，只是换「要传给引擎的地点」：
;        5 = **优先「行星自己的地点」**（Planet.GetLocation()——引擎的星图节点就是
;            按地点查表的，城市/内部地点常常只是行星地点的子地点；这是第 40 轮的新默认）；
;        6 = 引导引用的当前/编辑地点**原样**（第 37~39 轮的行为）；
;        7 = 沿父地点链找到的第一个**带行星**的地点。
;        为什么要三个候选：玩家反馈「R 能打开星图，但所有任务都指到沃利阿尔法星」。
;        DLL 在「星图没打开」时会自动重试并依次切换这三个候选（见 SAQ.cpp 的
;        kStarMapRetryMs），日志里能看出哪一次把星图打开了。
;
;  ## SAQ_Notify = 7777 + 菜单打开次数
;
;  两个用途：
;    ① 给 DLL 当**身份锚点**：插件自己在加载顺序里的序号看不出（FormID 前缀会变），
;       DLL 用「值落在 7777..8776」去认领这三个 GLOB（见 SAQ.cpp::ResolveEsmChannel）；
;    ② 证据链：值是 7777 ⇒ ESM 加载了、任务在跑、脚本活着；值在涨 ⇒ 脚本看得到菜单事件。
; ============================================================================

; DLL -> 脚本：引导目标的世界引用 FormID 的**低 24 位**（0 = 清除引导）
; ★ 第 21 轮：完整 FormID 拆成两个 GLOB —— 本属性存低 24 位，GuidePrefix 存高 8 位。
;   原因：GLOB 是 float（尾数 24 位），完整 FormID 超过 2^24（DLC 的引用，
;   如 0x0107BDB2 = 17,284,530）后**奇数不可精确表示**（会 ±1，指向相邻记录）。
;   拆开后（低 24 位 ≤0xFFFFFF、高 8 位 ≤0xFF）两个分量都精确。
GlobalVariable Property GuideTargetRef Auto

; DLL -> 脚本：引导目标 FormID 的**高 8 位**（= master 序号）。旧 ESM 没有这条记录时
; 属性为 None ⇒ 按历史行为处理（GuideTargetRef 本身就是完整 FormID）。
GlobalVariable Property GuidePrefix Auto

; 脚本 -> DLL：处理结果（见上面取值表）
GlobalVariable Property GuideState Auto

; 脚本 -> DLL：身份锚点 + 菜单打开计数（见上面说明）
GlobalVariable Property NotifyFlag Auto

; ★ 第 37 轮：星图请求的「待打开目标」（菜单关闭事件里记下，随后由轮询节拍执行）
; ★ 第 42 轮：再加一个「待打开目标的 FormID」—— 执行时与通道里的**当前**目标核对，
;   不一致就放弃（见 ProcessStarMapPending 与 ApplyGuide 的说明）。
ObjectReference StarMapPendingRef = None
int StarMapPendingFormID = 0

; ★★ 第 44 轮：「还要等几个轮询节拍才打开星图」。
;   为什么不用独立定时器（第 37~43 轮的 StarMapDelay/StarMapTimerID）：实测（18:34~18:35
;   会话）三次按 R 那个 1.5 秒定时器**一次都没跑到** —— 星图被界面侧更早的 dispatch
;   打开（那个 dispatch 用代理任务**上一次**的目标位置，见 MissionMenu.as 的
;   SaqNoteStarMapHandoff），星图是暂停菜单 ⇒ 游戏暂停 ⇒ 定时器冻结。
;   现在 dispatch 已删掉，改由**轮询定时器**（0.5 秒一拍）推进：轮询定时器只在游戏
;   运行时才走，「节拍到点」本身就意味着「菜单关闭动画已过、游戏在跑」—— 正是引擎
;   接受 ShowGalaxyStarMapMenuAndPlotToLocation 的时机，也不会被暂停吃掉。
int StarMapPendingTicks = 0

; 本任务里引导目标用的别名 id 与目标索引（与 patch_saq_esm.py 保持一致）
; ★ Starfield 的 Papyrus 4.7 里没有 AutoConst 这个 flag（实测报 "Unknown user flag autoconst"），
;   常量属性要用 AutoReadOnly。
int Property GuideAliasID = 0 AutoReadOnly
int Property GuideObjectiveID = 10 AutoReadOnly

; 身份锚点初值（DLL 认这几个 GLOB 用的）
float Property NotifyMagic = 7777.0 AutoReadOnly

; 轮询间隔与定时器 id
float Property PollInterval = 0.5 AutoReadOnly
int Property PollTimerID = 1 AutoReadOnly

; ★ 第 37 轮：星图请求的延时与定时器 id。
;   ★★ 第 44 轮起**不再使用**（历史遗留，保留声明只为读旧存档时不缺属性）：
;   延时的角色已由 StarMapPendingTicks + 轮询节拍接管（见上面的说明）。
;   历史：第 37 轮 0.5 秒、第 40 轮拉到 1.5 秒 —— 当时观察到的「星图没开」其实是
;   界面侧 dispatch 抢先把星图打开后、脚本这条路被暂停冻住造成的（第 44 轮定案）。
float Property StarMapDelay = 1.5 AutoReadOnly
int Property StarMapTimerID = 2 AutoReadOnly

; ★ 第 40 轮：本次星图请求要用的「地点候选」（DLL 写进 SAQ_GuideState 的值，见 ApplyGuide）。
;   5 = 优先「行星自己的地点」（Planet.GetLocation()，默认）；6 = 引用当前/编辑地点原样；
;   7 = 父地点链里第一个带行星的地点。DLL 的自动重试会依次换 5 → 6 → 7。
int StarMapPendingMode = 5

Event OnInit()
	Debug.Trace("[SAQ] SAQ_Main OnInit —— 注册菜单事件 + 启动引导轮询")
	If NotifyFlag != None
		NotifyFlag.SetValue(NotifyMagic)
	EndIf
	If GuideState != None
		; ★ 初值写 3（=已清除）而不是 0：0 是「有新请求」，写成 0 会让第一次轮询
		;   白跑一次「清除引导」（虽然无害，但日志里会多一条没意义的记录）。
		GuideState.SetValue(3)
	EndIf
	; ★ 第 16 轮：脚本重挂自愈。
	;   读档/任务重启会让本脚本重新 OnInit（实测一次游戏会话里 OnInit 跑了 3 次），
	;   重挂会把别名清空（游戏里的蓝点随之消失），但 GLOB 里可能还留着引导目标
	;   （DLL 那边认为引导还在）。把状态置回 0（待处理），让定时器立刻重新应用一次。
	If GuideTargetRef != None && GuideState != None && GuideTargetRef.GetValue() > 0.0
		GuideState.SetValue(0)
		Debug.Trace("[SAQ] 脚本重挂且引导目标仍在 —— 重新应用引导")
	EndIf
	RegisterForMenuOpenCloseEvent("BSMissionMenu")
	StartTimer(PollInterval, PollTimerID)
EndEvent

Event OnTimer(int aiTimerID)
	; 重新排下一拍（Starfield 的定时器是一次性的）。
	; ★★ 第 44 轮：不再按 id 分支 —— 旧存档里可能还留着一个 id=2 的定时器
	;   （第 37~43 轮的 StarMapTimerID），让它照常走「重挂轮询 + 应用引导 + 推进星图待办」，
	;   与轮询节拍完全同构（重挂同一个 id 只是重置，无副作用）。
	StartTimer(PollInterval, PollTimerID)
	ApplyGuide()
	; ★★ 第 44 轮：星图待办改由**轮询节拍**推进（见 ProcessStarMapPending）。
	;   放在 ApplyGuide 之后：这一拍刚装上的待办（DLL 在游戏运行中重发的 5/6/7）
	;   也从这里开始倒数，不会漏。
	ProcessStarMapPending()
EndEvent

Event OnMenuOpenCloseEvent(String asMenuName, Bool abOpening)
	If asMenuName != "BSMissionMenu"
		Return
	EndIf
	If abOpening
		; ★ 第 26 轮：每次开菜单都重挂一次定时器（重复调用同一 id 只是重置，无副作用）。
		;   起因：脚本实例**从存档恢复时 OnInit 不跑**（第 26 轮实测）⇒ OnInit 里的
		;   StartTimer 从来没执行过 ⇒ 世界里没有任何轮询机会；这里补挂一次。
		;   ★ 第 27 轮实测更正：菜单**开着**时 Papyrus 定时器不触发（菜单暂停游戏 ⇒
		;   StartTimer 不走）—— 「菜单开着时 0.5 秒内生效」做不到，也不需要：
		;   引导应用发生在「菜单关闭」分支（与原版交互一致）。重挂的实际作用是
		;   保证**菜单关着（世界里）**时轮询可用，例如 DLL 在菜单关着时重发的请求。
		StartTimer(PollInterval, PollTimerID)
		; 顺手补一次（零开销：GuideState != 0 立即返回）—— 处理「菜单关着时 DLL 重发的请求」
		; （那种重发没人触发 OnTimer/关闭事件，只能等这次开菜单）。
		ApplyGuide()
		; 证据：菜单开过 ⇒ 这条脚本在跑、且看得到菜单事件（DLL 会读这一位写日志）
		If NotifyFlag != None
			NotifyFlag.SetValue(NotifyFlag.GetValue() + 1.0)
			; ★ 第 19 轮：每次菜单打开都在 Papyrus 日志里留一条 —— 这是「脚本活性」的
			;   直接证据（第 18 轮实测：一次会话里 Papyrus 日志没有任何 SAQ 痕迹，
			;   而 DLL 侧无法区分「脚本僵死」和「DLL 读得早」）。
			;   DLL 侧会比对「开菜单 1.5 秒后通知值有没有 +1」，与本行互为佐证。
			Debug.Trace("[SAQ] 菜单打开 通知=" + (NotifyFlag.GetValue() as int))
		EndIf
		Return
	EndIf
	; 关菜单：HUD 要露出来了，顺手立刻应用一次（不用等下一拍轮询）
	ApplyGuide()
EndEvent

Function ApplyGuide()
	If GuideTargetRef == None || GuideState == None
		Debug.Trace("[SAQ] 引导失败：GLOB 属性没绑上（GuideTargetRef/GuideState 为空）")
		Return
	EndIf
	float pendingState = GuideState.GetValue()
	; ★ 第 37 轮：5 = 待处理 + 应用后打开星图（玩家按了「设定航线」）。
	;   0 = 普通待处理（脚本自己下发的重发/动态更新/自愈都走这个值）。
	;   ★ 第 40 轮：6/7 = 同 5，只是换「要传给引擎的地点」（DLL 重试时用，见文件头状态表）。
	Bool starMapWanted = (pendingState == 5.0) || (pendingState == 6.0) || (pendingState == 7.0)
	If !starMapWanted && pendingState != 0.0
		; 没有新的请求（1/2/3/4 都表示上一轮已经处理完）
		Return
	EndIf

	; ★ 第 42 轮：**任何一次新请求**都先把上一条「待打开的星图」作废（下面 starMapWanted
	;   分支会重新装上）。否则：R（待开星图）→ 这段窗口里玩家又引导了别的任务/取消引导 →
	;   旧待办仍然躺在那里，节拍到点就把**上一条任务**的航线开出来
	;   —— 玩家看到的就是「导航的目标不是我选的那条」。
	StarMapPendingRef = None
	StarMapPendingFormID = 0
	StarMapPendingTicks = 0

	ReferenceAlias guideAlias = GetAlias(GuideAliasID) as ReferenceAlias
	If guideAlias == None
		Debug.Trace("[SAQ] 引导失败：别名 " + GuideAliasID + " 不存在（ESM 补丁没生效？）")
		GuideState.SetValue(4)
		Return
	EndIf

	; ★ 第 21 轮：把「低 24 位 + 高 8 位」拼回完整 FormID（见 GuideTargetRef 的说明）。
	;   旧 ESM（没有 GuidePrefix）时按历史行为：GuideTargetRef 里就是完整 FormID。
	;   ★ 第 42 轮：拼装逻辑收进 CurrentGuideTargetFormID()（定时器到点的过期校验也要用同一套）。
	int targetFormID = CurrentGuideTargetFormID()
	If targetFormID <= 0
		; 清除引导（玩家取消了，或者那条任务已经被接取）
		guideAlias.Clear()
		SetObjectiveDisplayed(GuideObjectiveID, False)
		SetActive(False)
		GuideState.SetValue(3)
		Debug.Trace("[SAQ] 引导已清除")
		Return
	EndIf

	ObjectReference target = Game.GetForm(targetFormID) as ObjectReference
	If target == None
		Debug.Trace("[SAQ] 引导失败：FormID " + targetFormID + " 取不到引用")
		GuideState.SetValue(2)
		Return
	EndIf

	guideAlias.ForceRefTo(target)
	SetObjectiveDisplayed(GuideObjectiveID, True, True)
	SetActive(True)
	GuideState.SetValue(1)
	Debug.Trace("[SAQ] 引导已应用：" + target)

	; ★ 第 37 轮：玩家按了「设定航线（R）」—— 应用完引导后打开星图并把航线画到
	;   接取地点（引擎原生函数，只负责「打开 + 定位 / 设航线」，引导本身不受影响）。
	;   本函数多半是在「任务菜单关闭」事件里被调用，那一刻菜单还在销毁流程里，
	;   直接开另一个菜单容易被引擎吞掉 ⇒ 装进待办，由下一个**轮询节拍**执行。
	;   ★★ 第 44 轮：原来是「StartTimer(StarMapDelay=1.5, StarMapTimerID)」，实测
	;   三次按 R 一次都没跑到（星图被界面侧 dispatch 提前打开 ⇒ 暂停 ⇒ 定时器冻结；
	;   见 StarMapPendingTicks 的说明）。现在节拍本身就要求「游戏在运行」，不会被冻结吃掉。
	;   ★ 第 42 轮：这段窗口里玩家可能又换了引导 ⇒ 执行时用 StarMapPendingFormID
	;   与通道当前目标核对，不一致就跳过（见 ProcessStarMapPending）。
	If starMapWanted
		StarMapPendingRef = target
		StarMapPendingFormID = targetFormID
		StarMapPendingMode = pendingState as int
		StarMapPendingTicks = 1
		Debug.Trace("[SAQ] 星图请求：下一个轮询节拍（约 0.5 秒）打开（目标 " + FormText(target) + "，FormID=" + targetFormID + "，地点候选=" + StarMapPendingMode + "）")
	EndIf
EndFunction

; ============================================================================
;  ★ 第 42 轮：通道里「此刻的引导目标」的完整 FormID（低 24 位 + 高 8 位）。
;  由 ApplyGuide() 与 ProcessStarMapPending() 共用 —— 后者用来判断「待打开的星图」
;  还是不是当前这条引导（玩家可能在这段窗口里换了任务）。
; ============================================================================
int Function CurrentGuideTargetFormID()
	If GuideTargetRef == None
		Return 0
	EndIf
	float targetLocal = GuideTargetRef.GetValue()
	If GuidePrefix != None
		Return ((GuidePrefix.GetValue() as int) * 16777216) + (targetLocal as int)
	EndIf
	Return targetLocal as int
EndFunction

; ============================================================================
;  ★★ 第 44 轮：星图待办的执行（由**轮询节拍**调用，见 StarMapPendingTicks）。
;
;  1) 每次新请求（ApplyGuide 的 starMapWanted 分支）把待办装上、Ticks = 1；
;  2) 本函数每一拍先把 Ticks 减 1，减到 0 的那一拍才真正调用引擎 —— 于是
;     「菜单关闭动画已经走完、游戏确认在运行」这两个条件天然满足：轮询定时器
;     只在游戏运行时才走（第 27 轮定案：菜单开着 = 暂停 = 定时器冻结）；
;  3) 到点时做**过期校验**（第 42 轮）：待办目标必须仍是通道里的当前目标，
;     否则说明玩家在这段时间里又换了引导/取消 —— 丢掉，不打开星图
;     （否则会把**上一条**任务的航线开出来）。
;
;  实测背景（第 44 轮，18:34~18:35 会话）：原来的「StartTimer(1.5, StarMapTimerID)」
;  三次按 R **一次都没跑到** —— 界面侧那条原版 dispatch 抢先把星图打开了（用的是
;  代理任务上一次的目标位置），星图是暂停菜单 ⇒ 游戏暂停 ⇒ 定时器冻结 ⇒ 本函数
;  永远等不到节拍。dispatch 删除后（见 MissionMenu.as 的 SaqNoteStarMapHandoff），
;  这里成为打开星图的**唯一**入口。
; ============================================================================
Function ProcessStarMapPending()
	If StarMapPendingRef == None
		Return
	EndIf
	If StarMapPendingTicks > 0
		StarMapPendingTicks -= 1
		Return
	EndIf
	; 先把待办取出来并清空（避免 OpenStarMapFor 里重入时重复打开）
	ObjectReference pendingTarget = StarMapPendingRef
	int pendingFormID = StarMapPendingFormID
	int pendingMode = StarMapPendingMode
	StarMapPendingRef = None
	StarMapPendingFormID = 0
	StarMapPendingTicks = 0
	; ★ 第 42 轮：过期校验（见上面的第 3 点）
	int nowFormID = CurrentGuideTargetFormID()
	If pendingFormID != nowFormID
		Debug.Trace("[SAQ] 星图请求已过期：待办目标 " + pendingFormID + " ≠ 当前目标 " + nowFormID + "（引导已换/已取消）—— 跳过打开星图")
		Return
	EndIf
	OpenStarMapFor(pendingTarget, pendingMode)
EndFunction

; ============================================================================
;  ★ 第 37 轮：SET COURSE（键盘 R / 手柄 X）的「星图」这一半
;
;  玩家按 R 时：① 界面侧（第 38 轮新协议）收到 C++ 成功回写后走原版「退回游戏」
;  路径把整个暂停菜单关掉；② 本脚本在「菜单关闭」事件里应用引导并把待办装上；
;  ③ **下一拍轮询节拍**（ProcessStarMapPending）调用本函数 —— 那一刻菜单关闭动画
;  已走完、游戏已恢复运行。
;
;  ★★ 第 44 轮：本函数的唯一调用点是 ProcessStarMapPending。
;  第 36 轮那条「照抄原版」的 AS3 dispatch（MissionMenu_PlotToLocation）**实测是有效的**
;  （第 37 轮的「无 sink」结论被 18:34~18:35 会话日志推翻），但它用的是代理任务
;  **上一次**的目标位置 ⇒ 星图位置永远滞后一条；而且它先把星图打开、游戏一暂停，
;  本函数就再也跑不到（这正是玩家反馈「R 打开的星图位置永远是上一条任务」的病根）。
;  现在 dispatch 已删除，这里成为唯一入口，调的是引擎真正实现了的能力：
;    Game.ShowGalaxyStarMapMenuAndPlotToLocation(Location)
;  = 打开星图 + 把航线画到那个地点（原版 SET COURSE 的同款行为）。
;
;  取「接取地点」的办法（按可靠性排序）：
;    ① akTarget.GetCurrentLocation()  —— 引用所在位置（引用已加载时最准）；
;    ② akTarget.GetEditorLocation()   —— 数据里的放置位置（引用没加载时仍然有值）；
;  两者都拿不到就不调引擎函数（避免拿 None 去调、弹一条「Location passed was null.」）。
;
;  ★ 第 38 轮：加两道保险 + 一行诊断（回应玩家反馈「星图显示的还是我所在的星球 /
;   R 键不会帮我选中这个任务」）：
;    ① 引擎是按「地点 → 行星」解析目的地的 ⇒ 先把地点的行星查出来进日志
;       （GetCurrentPlanet；玩家再报「指错星球」时，这一行就能证明我们传的是什么）；
;    ② 地点自己查不到行星时，沿父地点链往上找第一个**带行星**的地点再传给引擎
;       （传一个解析不出行星的地点，引擎只会把星图按默认焦点打开 —— 表现就是
;       「显示我所在的星球、没有任务导航点」）。
;
;  ★ 第 40 轮：三个候选 + 一行「采用」诊断（回应玩家反馈「R 能打开星图，但所有任务
;   都指到沃利阿尔法星」）。离线结论（docs/05 第十节~）：引擎的
;   `ShowGalaxyStarMapMenuAndPlotToLocation` 第一步是 `0xac2ab0(&节点, 地点)` ——
;   **按「地点表单」查星图节点表**，查不到只会按「当前位置」打开星图。而引擎自己的
;   `Location.GetCurrentPlanet()` 用的就是同一个解析器（0x1FEACE0）⇒ 「地点 → 行星」
;   能成立并不代表「地点 → 星图节点」能成立。所以要试的出入口有三个：
;     ① `body.GetLocation()`（行星自己的地点 —— 星图节点是按行星/星系地点登记的，
;        城市/内部地点常常只是它的子地点）★ 现在的默认候选（DLL 状态 5）；
;     ② 引用自己的当前/编辑地点（第 37~39 轮的行为，DLL 状态 6 = 重试时换它）；
;     ③ 父地点链里第一个带行星的地点（DLL 状态 7 = 再换它）。
;   三个候选各带一次，日志里「采用地点=…」这一行就是「这一轮传了什么」的硬证据。
;
;  ★★ 第 45 轮补丁（实机日志复查：「朱诺的计谋」星图里没有目标位置）：
;   地点链里**一个行星都没有**时（目标在飞船内部 / 引擎动态创建的内部地点，实例 =
;   MS03JunoShip_CreatedInteriorLocationDungeon），星图节点表里根本没有这种位置
;   （引擎只登记星系/星球层）——打开星图只会停在默认焦点（玩家当前位置）。
;   此时**不打开星图**，改发一条 HUD 通知如实说明（避免「星图里没有目标」看起来像坏了）；
;   世界里的任务标记/扫描仪路径线不受影响（跟随它即可）。
;   DLL 侧配套：`星图诊断` 全层节点=0 时不重试、超时文案改成「按预期未打开」。
; ============================================================================
Function OpenStarMapFor(ObjectReference akTarget, int aiMode)
	If akTarget == None
		Debug.Trace("[SAQ] 星图请求：引导目标引用为空，跳过")
		Return
	EndIf
	Location loc = akTarget.GetCurrentLocation()
	If loc == None
		loc = akTarget.GetEditorLocation()
	EndIf
	If loc == None
		Debug.Trace("[SAQ] 星图请求失败：取不到目标地点（" + akTarget + "）")
		Return
	EndIf

	; ---- 收集候选（顺便把整条地点链打进日志，方便离线核对「引擎认哪一层」）----
	Planet body = loc.GetCurrentPlanet()
	Location parentWithPlanet = None
	Location[] parents = loc.GetParentLocations()
	int i = 0
	While i < parents.Length
		Location parentLoc = parents[i]
		If parentLoc != None
			Planet parentBody = parentLoc.GetCurrentPlanet()
			If parentBody != None
				If body == None
					body = parentBody
				EndIf
				If parentWithPlanet == None
					parentWithPlanet = parentLoc
				EndIf
			EndIf
			Debug.Trace("[SAQ] 星图请求：父地点[" + i + "]=" + FormText(parentLoc) + "（ID=" + FormIDText(parentLoc) + "，行星=" + FormText(parentBody) + "，行星ID=" + FormIDText(parentBody) + "）")
		EndIf
		i += 1
	EndWhile
	Location bodyLoc = None
	If body != None
		bodyLoc = body.GetLocation()
	EndIf

	; ---- 按候选挑一个传给引擎（默认 5 = 优先「行星自己的地点」）----
	Location plotLoc = loc
	int used = aiMode
	If aiMode == 7
		If parentWithPlanet != None
			plotLoc = parentWithPlanet
		Else
			used = 6
		EndIf
	EndIf
	If used != 7 && used != 6
		If bodyLoc != None
			plotLoc = bodyLoc
			used = 5
		Else
			used = 6
		EndIf
	EndIf

	; ★★ 第 45 轮补丁（实机日志复查：任务「朱诺的计谋」星图里没有目标位置）：
	;   目标的地点在飞船内部 / 引擎**动态创建**的内部地点时（实例：
	;   MS03JunoShip_CreatedInteriorLocationDungeon），它不在星图节点表里
	;   （引擎只登记星系/星球层）——行星=None、父地点链里也没有行星。
	;   此时 ShowGalaxyStarMapMenuAndPlotToLocation 只会把星图按**默认焦点**
	;   （玩家当前位置）打开：玩家看到「星图里没有目标」，像坏了。
	;   按 AGENTS.md「不可引导要提示玩家」的精神：这里**不打开星图**，改发一条
	;   HUD 通知如实说明（世界里的任务标记/扫描仪路径线不受影响，跟随它即可）。
	;   （DLL 侧同款判定：`星图诊断` 全层节点=0 时不重试、超时文案改「按预期未打开」。）
	If body == None
		Debug.Trace("[SAQ] 星图请求：目标地点不在星图上（行星=None、父地点链无行星；位置可能在飞船内部/动态创建的内部地点）—— 不打开星图，改发 HUD 提示")
		Debug.Notification("该目标不在星图上（飞船内/太空），请跟随任务标记 / Target not on the star map")
		Return
	EndIf

	Debug.Trace("[SAQ] 星图请求：打开星图并设定航线 → " + FormText(akTarget) + " @ " + FormText(loc) + "（ID=" + FormIDText(loc) + "，行星=" + FormText(body) + "，行星地点=" + FormText(bodyLoc) + "，父地点候选=" + FormText(parentWithPlanet) + "，候选号=" + used + "，采用地点=" + FormText(plotLoc) + "（ID=" + FormIDText(plotLoc) + "））")
	Game.ShowGalaxyStarMapMenuAndPlotToLocation(plotLoc)
EndFunction

; ============================================================================
;  ★ 第 40 轮：日志小工具 —— Papyrus 里把「可能为 None 的表单」拼进字符串很容易踩坑
;  （None 与字符串相加的行为没保证），统一走这两个函数。
; ============================================================================
String Function FormText(Form akForm)
	If akForm == None
		Return "None"
	EndIf
	Return "" + akForm
EndFunction

String Function FormIDText(Form akForm)
	If akForm == None
		Return "-"
	EndIf
	Return "" + (akForm.GetFormID() as int)
EndFunction
