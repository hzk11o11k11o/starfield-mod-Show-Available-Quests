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
;  ## SAQ_GuideState 的取值（DLL 写 0/5，脚本写 1/2/3/4）
;
;    0 = 待处理（DLL 每次下新目标都会置 0）
;    1 = 已应用（ForceRefTo + 显示目标 + 设为追踪）
;    2 = 目标引用取不到（Game.GetForm 返回 None —— FormID 不对 / 表单没加载）
;    3 = 已清除（DLL 传 0：取消引导）
;    4 = 别名不存在（ESM 没打补丁 / 别名 id 变了）
;    5 = ★ 第 37 轮：待处理 + **应用完打开星图**（玩家在「可接任务」里按了
;        「设定航线（R）」）。DLL 用引擎的 UI 消息（kHide）把任务菜单关掉，
;        本脚本随即在「菜单关闭」事件里跑：① 照常应用引导；② 取引导目标的
;        地点（GetCurrentLocation / GetEditorLocation），调用引擎原生的
;          Game.ShowGalaxyStarMapMenuAndPlotToLocation(地点)
;        打开星图并把航线画到那里（= 原版 SET COURSE 的同款能力）。
;        为什么必须这么绕：任务菜单开着时 Papyrus 定时器不走（第 27 轮实测定案），
;        脚本只能在菜单关闭时跑；而 DLL 直接调 Papyrus 原生函数要伪造 VM 栈帧，
;        风险远大于收益（详见 docs/05 第十一节）。
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

; ★ 第 37 轮：星图请求的「待打开目标」（菜单关闭事件里记下，延后 0.5 秒执行）
ObjectReference StarMapPendingRef = None

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

; ★ 第 37 轮：星图请求的延时与定时器 id（见 OpenStarMapFor 的说明）。
;   为什么不在「菜单关闭」事件里直接调：那一刻菜单还在销毁流程里，
;   延后 0.5 秒（菜单关掉后游戏已恢复运行 ⇒ 定时器会走）更稳。
float Property StarMapDelay = 0.5 AutoReadOnly
int Property StarMapTimerID = 2 AutoReadOnly

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
	; ★ 第 37 轮：星图请求的延后执行（先把待办取出来再调，避免重入时重复打开）
	If aiTimerID == StarMapTimerID
		ObjectReference pendingTarget = StarMapPendingRef
		StarMapPendingRef = None
		OpenStarMapFor(pendingTarget)
		Return
	EndIf
	; 重新排下一拍（Starfield 的定时器是一次性的）
	StartTimer(PollInterval, PollTimerID)
	ApplyGuide()
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
	Bool starMapWanted = (pendingState == 5.0)
	If !starMapWanted && pendingState != 0.0
		; 没有新的请求（1/2/3/4 都表示上一轮已经处理完）
		Return
	EndIf

	ReferenceAlias guideAlias = GetAlias(GuideAliasID) as ReferenceAlias
	If guideAlias == None
		Debug.Trace("[SAQ] 引导失败：别名 " + GuideAliasID + " 不存在（ESM 补丁没生效？）")
		GuideState.SetValue(4)
		Return
	EndIf

	; ★ 第 21 轮：把「低 24 位 + 高 8 位」拼回完整 FormID（见 GuideTargetRef 的说明）。
	;   旧 ESM（没有 GuidePrefix）时按历史行为：GuideTargetRef 里就是完整 FormID。
	float targetLocal = GuideTargetRef.GetValue()
	int targetFormID
	If GuidePrefix != None
		targetFormID = ((GuidePrefix.GetValue() as int) * 16777216) + (targetLocal as int)
	Else
		targetFormID = targetLocal as int
	EndIf
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
	;   这里**延后 0.5 秒**执行：本函数多半是在「任务菜单关闭」事件里被调用的，
	;   那一刻菜单还在销毁流程里，直接开另一个菜单容易被引擎吞掉（见 OpenStarMapFor）。
	If starMapWanted
		StarMapPendingRef = target
		StartTimer(StarMapDelay, StarMapTimerID)
		Debug.Trace("[SAQ] 星图请求：" + StarMapDelay + " 秒后打开（目标 " + target + "）")
	EndIf
EndFunction

; ============================================================================
;  ★ 第 37 轮：SET COURSE（键盘 R / 手柄 X）的「星图」这一半
;
;  玩家按 R 时 DLL 会：① 写引导目标 + 把 GuideState 置 5（= 要打开星图）；
;  ② 用引擎的 UI 消息（kHide）关掉任务菜单 —— 本脚本才能在「菜单关闭」事件里跑到。
;  本函数由**延时定时器**（StarMapTimerID，0.5 秒）调用，不在关闭事件里直接调。
;
;  为什么必须是**引擎原生函数**（而不是第 36 轮那条「照抄原版」的 AS3 dispatch）：
;  离线复核证明 `MissionMenu_PlotToLocation` 这个事件在整个 exe 里**没有任何 C++ sink**
;  （详见 docs/05 第十一节）⇒ 只能调引擎真正实现了的能力：
;    Game.ShowGalaxyStarMapMenuAndPlotToLocation(Location)
;  = 打开星图 + 把航线画到那个地点（原版 SET COURSE 的同款行为）。
;
;  取「接取地点」的办法（按可靠性排序）：
;    ① akTarget.GetCurrentLocation()  —— 引用所在位置（引用已加载时最准）；
;    ② akTarget.GetEditorLocation()   —— 数据里的放置位置（引用没加载时仍然有值）；
;  两者都拿不到就不调引擎函数（避免拿 None 去调、弹一条「Location passed was null.」）。
; ============================================================================
Function OpenStarMapFor(ObjectReference akTarget)
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
	Debug.Trace("[SAQ] 星图请求：打开星图并设定航线 → " + akTarget + " @ " + loc)
	Game.ShowGalaxyStarMapMenuAndPlotToLocation(loc)
EndFunction
