Scriptname SAQ_Main extends Quest

; ============================================================================
;  Starfield Show Available Quests - 主 Papyrus 脚本
;  绑定在 SAQ_ShowAvailableQuests.esm 的 SAQ_MainQuest 上（Start Game Enabled）
;
;  职责（MVP）：
;    1) 证明 ESM -> 脚本 -> GLOB 这条链路可用（DLL 会读 GLOB 打日志）
;    2) 菜单打开时给 DLL 一个信号（DLL 侧自己也能轮询，这里是双保险）
;  预留（引导功能）：
;    3) DLL 写 GuideTargetRef = 目标 FormID；脚本把玩家导向该目标
;       （引擎不会追踪"未接取的任务"，所以用本 quest 当代理引导）
; ============================================================================

; DLL -> 脚本：引导目标的 FormID（0 = 清空）
GlobalVariable Property GuideTargetRef Auto

; 脚本 -> DLL：诊断状态（0 = 空闲，1 = 已处理，2 = 目标取不到）
GlobalVariable Property GuideState Auto

; 脚本 -> DLL：菜单打开信号（DLL 读后不必归零，只用于打日志）
GlobalVariable Property NotifyFlag Auto

Event OnInit()
	Debug.Trace("[SAQ] SAQ_Main OnInit, registering menu events")
	RegisterForMenuOpenCloseEvent("BSMissionMenu")
	If GuideState != None
		GuideState.SetValue(0)
	EndIf
EndEvent

Event OnMenuOpenCloseEvent(String asMenuName, Bool abOpening)
	If asMenuName == "BSMissionMenu" && abOpening
		If NotifyFlag != None
			NotifyFlag.SetValue(1)
		EndIf
	EndIf
EndEvent
