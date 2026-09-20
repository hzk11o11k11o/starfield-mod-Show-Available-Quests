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
;  0.5 秒一次的空判（GuideState != 0 直接返回）开销可以忽略，换来的是「什么时候写都能收到」。
;
;  ## 别名为什么用 GetAlias(0) 而不是脚本属性
;
;  VMAD 里的「别名属性」要写对 Object/Alias 联合体的字节格式，容易出错；
;  Quest.GetAlias(int) 原生函数直接按 id 取，零风险。
;
;  ## SAQ_GuideState 的取值（DLL 侧读它来判断脚本做完没有）
;
;    0 = 待处理（DLL 每次下新目标都会置 0）
;    1 = 已应用（ForceRefTo + 显示目标 + 设为追踪）
;    2 = 目标引用取不到（Game.GetForm 返回 None —— FormID 不对 / 表单没加载）
;    3 = 已清除（DLL 传 0：取消引导）
;    4 = 别名不存在（ESM 没打补丁 / 别名 id 变了）
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
	; 重新排下一拍（Starfield 的定时器是一次性的）
	StartTimer(PollInterval, PollTimerID)
	ApplyGuide()
EndEvent

Event OnMenuOpenCloseEvent(String asMenuName, Bool abOpening)
	If asMenuName != "BSMissionMenu"
		Return
	EndIf
	If abOpening
		; ★ 第 26 轮：每次开菜单都重挂一次定时器。
		;   实测（2026-09-20 三个会话的 Papyrus 日志）：脚本实例**从存档恢复时 OnInit 不跑**
		;   ⇒ OnInit 里的 StartTimer 从来没执行过 ⇒ 菜单开着时没有任何轮询机会，
		;   引导只在「菜单关闭」分支的 ApplyGuide() 里被应用（Papyrus `引导已应用` 的时间
		;   与 DLL 的「菜单关闭」一一对应）。DLL 侧旧逻辑会在菜单开着 11 秒后判「引导未生效」
		;   并清通道 —— 玩家挑条目久一点就真失效。这里把定时器补上（重复调用同一 id 只是重置，
		;   无副作用）：若引擎允许，菜单开着时 0.5 秒内就能应用引导。
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
	If GuideState.GetValue() != 0.0
		; 没有新的请求（0 才是待处理；1/2/3/4 都表示上一轮已经处理完）
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
EndFunction
