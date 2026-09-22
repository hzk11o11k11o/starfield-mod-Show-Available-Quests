package
{
   import Components.BSButton;
   import Shared.AS3.BS3DSceneRectManager;
   import Shared.AS3.BSAnimating3DSceneRect;
   import Shared.AS3.BSScrollingConfigParams;
   import Shared.AS3.BSTabbedSelection;
   import Shared.AS3.BSTabbedSelectionEvent;
   import Shared.AS3.Data.BSUIDataManager;
   import Shared.AS3.Data.FromClientDataEvent;
   import Shared.AS3.Events.CustomEvent;
   import Shared.AS3.Events.ScrollingEvent;
   import Shared.AS3.IMenu;
   import Shared.FactionUtils;
   import Shared.Components.ButtonControls.ButtonBar.ButtonBar;
   import Shared.Components.ButtonControls.ButtonData.ButtonBaseData;
   import Shared.Components.ButtonControls.ButtonData.ButtonData;
   import Shared.Components.ButtonControls.ButtonData.ReleaseHoldComboButtonData;
   import Shared.Components.ButtonControls.ButtonData.UserEventData;
   import Shared.Components.ButtonControls.ButtonFactory.ButtonFactory;
   import Shared.Components.ButtonControls.Buttons.ButtonBase;
   import Shared.Components.ButtonControls.Buttons.IButton;
   import Shared.Components.ButtonControls.Utils.ButtonKeyHelper;
   import Shared.GlobalFunc;
   import Shared.PlatformUtils;
   import Shared.QuestUtils;
   import flash.display.MovieClip;
   import flash.events.Event;
   import flash.events.TimerEvent;
   import flash.utils.Timer;
   
   [Embed(source="/_assets/assets.swf", symbol="symbol96")]
   public class MissionMenu extends IMenu
   {
      
      public static const LERP_DELAY_TIME:Number = 0.2;
      
      public static const MISSION_ANIMATION_DELAY_TIME:Number = 0.25;
      
      public static const MISSION_FADE_IN_TIME:Number = 0.4;
      
      public static const OBJECTIVE_ANIMATION_DELAY_TIME:Number = 0.1;
      
      public static const OBJECTIVE_FADE_IN_TIME:Number = 0.4;
      
      public static const OBJECTIVE_LIST_OFFSET:Number = 300;
      
      public static const KEYBOARD_TAB_BUTTON_OFFSET:Number = 1.25;
      
      private static const SHOW_ITEM_LOCATION_EVENT:String = "MissionMenu_ShowItemLocation";
      
      private static const MissionMenu_PlotToLocation:String = "MissionMenu_PlotToLocation";
      
      private static const MissionMenu_ToggleTrackingQuest:String = "MissionMenu_ToggleTrackingQuest";
      
      private static const MissionMenu_RejectQuest:String = "MissionMenu_RejectQuest";
      
      private static const MissionMenu_SaveOpenedId:String = "MissionMenu_SaveOpenedId";
      
      private static const MissionMenu_SaveCategoryIndex:String = "MissionMenu_SaveCategoryIndex";
      
      private static const MissionMenu_ClearState:String = "MissionMenu_ClearState";
      
      public static const MissionMenu_OnExitMissionMenu:String = "MissionMenu_OnExitMissionMenu";
      
      protected static const TIMELINE_CLOSE_EVENT:String = "TimelineCloseEvent";
      
      public static const MISSION_SELECTION_CHANGE_SOUND:String = "UIMenuMissionsMenuSelectionChange";
      
      public static const MISSION_CATEGORY_CHANGE_SOUND:String = "UIMenuMissionsMenuCategoryChange";
      
      public static const MISSION_SUBTASK_TOGGLE_SOUND:String = "UIMenuMissionsMenuSubtasksToggle";
      
      public static const MISSION_TRACKING_TOGGLE_ON_SOUND:String = "UIMenuMissionsMenuTrackingToggleOn";
      
      public static const MISSION_TRACKING_TOGGLE_OFF_SOUND:String = "UIMenuMissionsMenuTrackingToggleOff";
      
      public static const MISSION_SHOW_ON_MAP_SOUND:String = "UIMenuMissionsMenuShowOnMap";
      
      // ===================================================================
      //  SAQ（Show Available Quests）：新增「可接任务」tab
      //
      //  数据来源有两层，C++ 推送优先，没有推送时用内嵌的回退表：
      //    ① C++ 插件 Invoke("SetAvailableQuests", <载荷>)  —— 载荷协议见下
      //    ② SAQ_EMBEDDED_CHUNKS（构建时由 tools/esm/gen_quest_table.py 生成，
      //       tools/build-saq.ps1 替换掉下面的 /*__SAQ_EMBEDDED__*/ 标记）
      //
      //  载荷协议（一行一条，Tab 分隔，名字放最后）：
      //      SAQ1
      //      T\t<中文标题>\t<英文标题>
      //      Q\t<FormID>\t<type>\t<中文名>\t<英文名>
      //  兼容旧版 3 字段 Q 行（只有中文名 = 中英同名）。
      //
      //  语言判定放在 AS3 侧：**引擎推给 UI 的 QuestData 里就是本地化的任务名**，
      //  比 C++ 去读 INI（本机实测读不到 sLanguage）可靠得多。
      // ===================================================================
      
      private static const SAQ_TITLE_ZH:String = "可接任务";
      
      private static const SAQ_TITLE_EN:String = "Available";
      
      // ★ 第 27 轮：载荷里 type == 这个值 = 「无限任务入口」（任务板）条目。
      //   这类条目的 uID 是世界引用的 FormID（不是任务），子项与描述用专门文案
      //   （见 SaqBuildObjective / SaqDescriptionText）。
      private static const SAQ_ENTRY_TYPE:int = 100;
      
      // ★★ 第 80 轮：type == 101 = 「提供无限任务的 NPC」条目（贸易管理局商人 /
      //   追踪者联盟探员）—— 与任务板同属「入口」（uID 是世界引用的 FormID），
      //   但文案不同：子项「与他交谈（可重复任务）」+ 描述写明「可重复任务提供者」。
      //   名字里自带「（可重复）」前缀（C++ 侧数据加好，界面原样显示）。
      private static const SAQ_REPEAT_NPC_TYPE:int = 101;
      
      private static const SAQ_EMBEDDED_CHUNKS:Array = [/*__SAQ_EMBEDDED__*/];
      
      public var UniversalBackButton_mc:BSButton;
      
      public var ButtonBar_mc:ButtonBar;
      
      public var MissionsList_mc:MissionsList;
      
      public var MissionInfo_mc:MissionInfo;
      
      public var TabbedFilterSelection_mc:MissionTabbedSelection;
      
      public var Vignette_mc:MovieClip;
      
      public var PreviewSceneRect_mc:BSAnimating3DSceneRect;
      
      private var ButtonBarRefreshTimer:Timer = null;
      
      private var PreviousMissionIndex:int = -1;
      
      private var bClosing:Boolean = false;
      
      private var QuestData:Array = null;
      
      private var AvailableQuests:Array = null;
      
      private var RawAvailableQuests:Array = null;
      
      private var SaqSourcePayload:String = null;
      
      private var SaqSourceIsCpp:Boolean = false;
      
      private var SaqRawQuests:Array = null;
      
      private var SaqTitleZh:String = null;
      
      private var SaqTitleEn:String = null;
      
      private var SaqLangKnown:Boolean = false;
      
      private var SaqLangZh:Boolean = false;
      
      // ★ 第 51 轮：入口挂载自检 —— SaqPublishEntryPoint() 的执行结果
      // （"not-run" 还没跑 / "ok" 已挂好 / "no-root" root 取不到 / "ex:…" 抛异常）。
      private var SaqPublishNote:String = "not-run";
      
      private var SaqTabProbe:String = "-";

      private var SaqOurTabProbe:String = "-";

      private var SaqOurTabMaxList:int = -1;

      // ★ 第 19 轮：最近一次 FilterKnownQuests 过滤掉的「玩家已有」uID 名单（日志诊断用）。
      private var SaqDropList:String = "-";
      
      private var SaqDropCount:int = 0;
      
      // ★★ 第 89 轮（可重复任务）：最近一次 FilterKnownQuests 里「已完成但可重复 ⇒
      //   放行保留」的 uID 名单（日志探针 `rptk=` 用 —— 证明豁免在显示层真的生效：
      //   这类任务做完一次后**继续显示**在「可接任务」里，还能再接）。
      private var SaqRepeatKeptList:String = "-";
      
      private var SaqRepeatKeptCount:int = 0;

      // ---- 引导（第 10 轮）------------------------------------------------
      // 玩家在「可接任务」tab 里选中一条、按 Enter 或 SET COURSE（键盘 R / 手柄 X）时：
      //   SaqGuideSeq++ / SaqGuideQuest = 任务 FormID（0 = 取消）
      //   → C++ 侧（SAQ.cpp::PollGuideRequest）读到序号变化 → 把「引导目标引用」写进 ESM 的
      //     GLOB → Papyrus（SAQ_Main.psc）在那条代理任务上 ForceRefTo + 显示目标 + 设为追踪
      //   → 引擎画出任务标记（蓝点）与扫描仪路径线。
      // 为什么要绕这一圈：未接取的任务引擎根本不追踪，这是「借引擎的标记系统一用」。
      private var SaqGuideSeq:int = 0;

      private var SaqGuideQuest:Number = 0;

      // ★ 第 37 轮：这一次引导请求是不是「设定航线（R）」发出的 ——
      //   true 时 DLL 会把 GuideState 置 5（脚本应用引导后打开星图），
      //   并且由 DLL 关掉任务菜单（Papyrus 定时器在菜单开着时不走，见 docs/05 第十一节）。
      //   来自 Enter（点「前往接取地点」子项）的请求为 false：只要蓝点/路径线，不要星图。
      //   ★ 它随请求一起经 `SAQ_PeekGuide` 的第三段传给 DLL（`<序号>|<任务FormID>|<1/0>`）。
      private var SaqGuideWantMap:Boolean = false;

      // ★ 第 38 轮：等 C++ 回写成功后，由**界面侧**关掉整个暂停菜单（原版「退回游戏」路径）。
      //
      // 为什么需要：第 37 轮只让 DLL 用 kHide 隐藏「任务菜单」——但 Starfield 的暂停菜单
      // （DataMenu）是任务菜单的父级，只隐藏子菜单会停在「暂停菜单顶层」：游戏仍然暂停
      // ⇒ 脚本的 0.5 秒定时器走不动（Papyrus 定时器只在游戏运行时走）⇒ 星图要等玩家手动
      // 关掉暂停菜单才出现。玩家实测反馈正是这个：「有时候只是切换到了最外层主菜单」
      // 「打开了星图但要等好久（R 后 4~5 秒）」。
      //
      // 现在：收到 C++ 的成功回写后调 `CloseMenu(true)`（= 原版「按住返回键退回游戏」那条
      // 路径：播关闭动画 → OnTimelineCloseEvent → `GlobalFunc.CloseAllMenus()`），整个暂停
      // 菜单一步关完、游戏立刻恢复运行 ⇒ 定时器走得动 ⇒ 星图约 1 秒后就出现。
      // 同时把这件事经 `SAQ_PeekGuide` 的第四段告诉 DLL（它就不必再发 kHide 了）。
      private var SaqPendingCloseToGame:Boolean = false;

      // 最近一次引导动作（进报告，日志里能看出玩家点了什么）
      private var SaqGuideNote:String = "-";

      // ★ 第 36 轮：代理任务（SAQ_MainQuest）的运行期 FormID —— 由 C++ 载荷的 `P\t<FormID>`
      //   行推来（DLL 知道自己的加载前缀，见 SAQ_Guide.cpp）。用途：按 SET COURSE 时把它
      //   交给**原版**的 MissionMenu_PlotToLocation 流程 —— 引擎会打开星图、聚焦到
      //   「接取地点」所在的星球并询问玩家是否导航（这正是原版任务菜单按 R 的表现）。
      //   0 = 不知道（内嵌回退表 / 旧版 DLL）⇒ 跳过原版流程，只做我们自己的引导。
      private var SaqProxyQuestID:Number = 0;

      // ★ 第 42 轮：玩家最近一次按键（R / Enter）用的是**哪一行** —— 进 SAQ_Report 的 press=[…]。
      //
      //   为什么需要：玩家反馈「R 键的导航结果不太稳定，有时候导航的目标似乎不是鼠标悬停的
      //   任务的目标」。此前日志里只有「C++ 解析出来的任务」（引导请求：<任务名>），
      //   没有任何一行能证明**界面当时用的是哪一行** —— 是把 hover 判错的锅，还是 C++/脚本
      //   的锅，无法区分。加上这一格后，`界面状态[N]` 与 `引导请求：…` 两行并排就能对上：
      //     press=R@0x351a@平衡账目   ← 界面按键时用的条目（uID 十六进制 @ 名字）
      //     sel=idx=137:0x351a@平衡账目 ← 那一刻列表的选中项（鼠标悬停会更新它）
      //   两者 uID 不一致 ⇒ 按钮那一刻界面用的不是鼠标悬停的那一行（真 bug，可查）；
      //   一致而 C++ 收到的任务不同 ⇒ 问题在通道/静态表侧。格式用方括号包起来，
      //   C++ 侧按括号取值（名字里可能有空格，不能按空格切）。
      private var SaqLastPressNote:String = "-";

      // ★ 第 42 轮：最近一次「列表选中项变化」（鼠标悬停 / 键盘上下 / 程序设置都会触发）。
      private var SaqLastSelNote:String = "-";
      
      // ★ 第 43 轮：诊断 —— 最近收到的 user event（「事件名↓按下 / ↑松开」，最多 6 条）。
      //   为什么需要它（第 42 轮遗留）：第 42 轮给 R 键补了 `press=[R@…]` 记录，但玩家实测
      //   「悬停任务板按 R 没反应」时，日志里连 press 都没变化 —— 这有两种可能分不开：
      //     ① 按键根本没进任务菜单（上游 / 按键映射 / 被别的组件截住）；
      //     ② 事件进了按钮栏，但 SET COURSE 按钮被禁用 ⇒ 回调不执行（press 不更新）。
      //   有了 ev=[…] 一次就能分开：
      //     · 没有 XButton ⇒ 病在①；· 有 XButton↓↑ 但 press 不变 ⇒ 病在②（按钮禁用）。
      private var SaqEventLog:Array = new Array();
      
      // ★ 第 43 轮：诊断 —— 最近一次选中项变化时的按钮状态，进报告 btn=[…]。
      //   格式：our/std（是不是我们的条目）:plot=<0/1>:map=<0/1>
      //   （plot=SET COURSE / map=显示在地图上；1=启用、0=置灰）
      private var SaqLastBtnNote:String = "-";

      private var StoredLastOpenedIds:Array = null;
      
      private var StoredLastCategory:uint = 0;
      
      private var InitializedOpenedIds:Boolean = false;
      
      private var bReturningToGame:Boolean = false;
      
      private var FilterInfoA:Array;
      
      private var lastSelectedIndex:int = -1;
      
      private var bCollapsing:Boolean = false;
      
      private var bWithinMiscQuest:Boolean = false;
      
      private var miscQuestIndex:int = 0;
      
      private var scrollPositionAtTracking:int = -1;
      
      private var startingTabButtonYPosition:Number = 0;
      
      private var bWrappedAroundUp:Boolean = false;
      
      private var bSkipSelectionSounds:Boolean = false;
      
      private var KeyHelper:ButtonKeyHelper = null;
      
      private var bButtonBarInitialized:Boolean = false;
      
      private var canReject:Boolean = false;
      
      private var CanTrackOrUntrack:Boolean = false;
      
      private var ShowAllQTsBtnData:ButtonBaseData;
      
      private var ShowOnlyActiveQTsBtnData:ButtonBaseData;
      
      private var ToggleQTDisplayButton:IButton;
      
      private var ShowOnlyActiveQTs:Boolean = true;
      
      public function MissionMenu()
      {
         this.ShowAllQTsBtnData = new ButtonBaseData("$ToggleShowAllQTs",[new UserEventData("Select",this.ToggleQTDisplay)]);
         this.ShowOnlyActiveQTsBtnData = new ButtonBaseData("$ToggleShowOnlyActiveQTs",[new UserEventData("Select",this.ToggleQTDisplay)]);
         super();
         addFrameScript(8,this.frame9,16,this.frame17);
         MissionsListEntry.largeTextMode = true;
         this.PreviewSceneRect_mc.SetBackgroundColor(67504895);
         BS3DSceneRectManager.Register3DSceneRect(this.PreviewSceneRect_mc);
         gotoAndPlay("Open");
         addEventListener(TIMELINE_CLOSE_EVENT,this.OnTimelineCloseEvent);
         this.ButtonBar_mc.visible = false;
         this.PopulateTabs();
         this.MissionsList_mc.addEventListener(ScrollingEvent.SELECTION_CHANGE,this.onMissionSelectionChange);
         addEventListener(MissionsList.ITEM_ACTIVATED,this.onMissionListItemActivated);
         this.UniversalBackButton_mc.addEventListener(BSButton.BUTTON_CLICKED_EVENT,this.OnCancelEvent);
         var _loc1_:BSScrollingConfigParams = new BSScrollingConfigParams();
         _loc1_.VerticalSpacing = 3;
         _loc1_.EntryClassName = "MissionsListEntry";
         this.MissionsList_mc.Configure(_loc1_);
      }
      
      public function get currentFilterIndex() : int
      {
         return this.TabbedFilterSelection_mc.selectedIndex;
      }
      
      public function get currentFilterFlag() : int
      {
         return this.FilterInfoA[this.currentFilterIndex].flag;
      }
      
      private function get ShowOnMapButton() : IButton
      {
         return this.ButtonBar_mc.ShowOnMapButton_mc;
      }
      
      private function get PlotToLocationButton() : IButton
      {
         return this.ButtonBar_mc.PlotToLocationButton_mc;
      }
      
      private function get BackButton() : IButton
      {
         return this.ButtonBar_mc.BackButton_mc;
      }
      
      private function get RejectQuestButton() : IButton
      {
         return this.ButtonBar_mc.RejectButton_mc;
      }
      
      private function PopulateButtonBar() : void
      {
         var _loc1_:String = null;
         var _loc2_:String = null;
         if(!this.bButtonBarInitialized)
         {
            _loc1_ = this.KeyHelper.GetButtonNameForEvent("XButton","");
            if(_loc1_.length != 0)
            {
               this.bButtonBarInitialized = true;
               this.ButtonBar_mc.Initialize(ButtonBar.JUSTIFY_RIGHT);
               this.ToggleQTDisplayButton = ButtonFactory.AddToButtonBar("BasicButton",this.ShowOnlyActiveQTs ? this.ShowAllQTsBtnData : this.ShowOnlyActiveQTsBtnData,this.ButtonBar_mc);
               this.ButtonBar_mc.AddButtonWithData(this.ShowOnMapButton,new ButtonBaseData("$SHOWONMAP",[new UserEventData("YButton",this.OnShowOnMapEvent)],false,true));
               this.ButtonBar_mc.AddButtonWithData(this.PlotToLocationButton,new ButtonBaseData("$SET COURSE",[new UserEventData("XButton",this.OnPlotCourseEvent)],false,true));
               this.RejectQuestButton.Visible = this.canReject;
               this.ButtonBar_mc.AddButtonWithData(this.RejectQuestButton,new ButtonBaseData("$REJECT",[new UserEventData("R3",this.OnRejectQuest)],true,this.canReject));
               _loc2_ = "$EXIT HOLD";
               _loc2_ += "_LRG";
               this.ButtonBar_mc.AddButtonWithData(this.BackButton,new ReleaseHoldComboButtonData("$BACK",_loc2_,[new UserEventData("Cancel",this.OnCancelEvent),new UserEventData("",this.onCloseSubMenuToGame)]));
               (this.ShowOnMapButton as ButtonBase).RefreshButtonData();
               (this.PlotToLocationButton as ButtonBase).RefreshButtonData();
               (this.RejectQuestButton as ButtonBase).RefreshButtonData();
               (this.BackButton as ButtonBase).RefreshButtonData();
               this.ButtonBar_mc.RefreshButtons();
               this.ButtonBar_mc.redrawDisplayObject();
               this.ButtonBarRefreshTimer = new Timer(60,1);
               this.ButtonBarRefreshTimer.addEventListener(TimerEvent.TIMER,this.handleButtonBarRefreshTimer);
               this.ButtonBarRefreshTimer.start();
               this.onMissionSelectionChange();
            }
         }
      }
      
      private function handleButtonBarRefreshTimer(param1:TimerEvent) : *
      {
         this.ButtonBar_mc.visible = true;
         this.ButtonBarRefreshTimer = null;
      }
      
      private function UpdateRejectData(param1:Boolean) : void
      {
         if(param1 != this.canReject)
         {
            this.canReject = param1;
            this.RejectQuestButton.Visible = param1;
            this.ButtonBar_mc.RefreshButtons();
         }
      }
      
      private function PopulateTabs() : void
      {
         this.FilterInfoA = new Array();
         // ★ 「全部」这一位的掩码从 0xFFFFFFFF 改成 0xFFFFFFBF
         //   即去掉 (1 << AVAILABLE_QUEST_TYPE)：未接任务只在我们的 tab 里出现，
         //   不污染原版「全部」列表（否则一进菜单就看到一堆没有目标的条目）。
         this.FilterInfoA.push({
            "text":"$ALL",
            "flag":4294967231
         });
         this.FilterInfoA.push({
            "text":"$Main",
            "flag":1 << QuestUtils.MAIN_QUEST_TYPE
         });
         this.FilterInfoA.push({
            "text":"$Faction",
            "flag":1 << QuestUtils.FACTION_QUEST_TYPE
         });
         this.FilterInfoA.push({
            "text":"$Misc",
            "flag":1 << QuestUtils.MISC_QUEST_TYPE
         });
         this.FilterInfoA.push({
            "text":"$MISSION",
            "flag":1 << QuestUtils.MISSION_QUEST_TYPE
         });
         this.FilterInfoA.push({
            "text":"$Activity",
            "flag":1 << QuestUtils.ACTIVITY_QUEST_TYPE
         });
         this.FilterInfoA.push({
            "text":"$Completed",
            "flag":1 << QuestUtils.COMPLETED_QUEST_TYPE
         });
         this.FilterInfoA.push({
            "text":this.SaqTabTitle(),
            "flag":1 << QuestUtils.AVAILABLE_QUEST_TYPE
         });
         this.TabbedFilterSelection_mc.SetTabsData(this.FilterInfoA);
         this.TabbedFilterSelection_mc.addEventListener(BSTabbedSelectionEvent.NAME,this.onFilterChanged);
         this.startingTabButtonYPosition = this.TabbedFilterSelection_mc.LeftButton.y;
      }
      
      private function SetAvailableTabText(param1:String) : void
      {
         if(param1 != null && param1.length > 0 && this.FilterInfoA != null && this.FilterInfoA.length > 0)
         {
            if(this.FilterInfoA[this.FilterInfoA.length - 1].text == param1)
            {
               return;
            }
            this.FilterInfoA[this.FilterInfoA.length - 1].text = param1;
            this.TabbedFilterSelection_mc.SetTabsData(this.FilterInfoA);
         }
      }
      
      private function BuildMergedList() : Array
      {
         var _loc1_:Array = this.QuestData == null ? new Array() : this.QuestData;
         if(this.AvailableQuests != null && this.AvailableQuests.length > 0)
         {
            _loc1_ = _loc1_.concat(this.AvailableQuests);
         }
         return _loc1_;
      }
      
      private function FilterKnownQuests(param1:Array) : Array
      {
         if(param1 == null)
         {
            return null;
         }
         // ★★ 第 89 轮（可重复任务）：索引从「uID -> true」改成「uID -> 日志条目」——
         //   豁免判据要读条目的 bComplete（已完成 + 可重复 ⇒ 保留）。
         var _loc2_:Object = {};
         if(this.QuestData != null)
         {
            var _loc3_:int = 0;
            while(_loc3_ < this.QuestData.length)
            {
               _loc2_[this.QuestData[_loc3_].uID] = this.QuestData[_loc3_];
               _loc3_++;
            }
         }
         var _loc4_:Array = new Array();
         var _loc5_:int = 0;
         // ★ 第 19 轮：记录被过滤掉的 uID 名单（最多 12 条，进 SAQ_Report 的 drop=）。
         //   用途：C++ 的 `raw=` 与 `keep=` 差几条时，日志直接给出「是哪几条」，
         //   不用再人肉比对 qdata 名单（第 18 轮实测：raw=260 keep=257 少 3 条，无从确认）。
         var _loc6_:String = "";
         var _loc7_:int = 0;
         // ★★ 第 89 轮：被豁免保留（已完成 + 可重复）的 uID 名单（最多 6 条，进 rptk=）。
         var _loc8_:String = "";
         var _loc9_:int = 0;
         while(_loc5_ < param1.length)
         {
            var _loc10_:Object = _loc2_[param1[_loc5_].uID];
            // ★★ 第 89 轮（可重复任务）：这类任务「做完一次还能再接」——
            //   已完成（bComplete）⇒ **放行**（继续显示在「可接任务」里）；
            //   进行中的照旧隐藏（正在做，不需要在「可接」里重复出现）。
            //   bComplete 取不到（旧引擎条目 / 字段缺失）⇒ 不放行（保守 —— 维持老行为）。
            var _loc11_:Boolean = _loc10_ != null
               && param1[_loc5_].bSaqRepeatable == true
               && _loc10_.bComplete == true;
            if(!_loc10_ || _loc11_)
            {
               _loc4_.push(param1[_loc5_]);
               if(_loc11_ && _loc9_ < 6)
               {
                  _loc9_++;
                  _loc8_ += (_loc9_ > 1 ? "," : "") + param1[_loc5_].uID.toString(16);
               }
            }
            else if(_loc7_ < 12)
            {
               _loc7_++;
               _loc6_ += (_loc7_ > 1 ? "," : "") + param1[_loc5_].uID.toString(16);
            }
            _loc5_++;
         }
         this.SaqDropCount = _loc7_;
         this.SaqDropList = _loc7_ > 0 ? _loc6_ : "-";
         this.SaqRepeatKeptCount = _loc9_;
         this.SaqRepeatKeptList = _loc9_ > 0 ? _loc8_ : "-";
         return _loc4_;
      }
      
      // ------------------------------------------------------------------
      //  SAQ 主体
      // ------------------------------------------------------------------

      // 判断一段文本「像不像中文」：1 = 中文，-1 = 明确不是（拉丁/假名/谚文），
      // 0 = 判不出来（纯符号/数字/空）。
      private static function SaqNameVerdict(param1:String) : int
      {
         if(param1 == null || param1.length == 0)
         {
            return 0;
         }
         var _loc2_:int = 0;
         while(_loc2_ < param1.length)
         {
            var _loc3_:int = param1.charCodeAt(_loc2_);
            if(_loc3_ >= 12352 && _loc3_ <= 12543)
            {
               return -1;
            }
            if(_loc3_ >= 44032 && _loc3_ <= 55215)
            {
               return -1;
            }
            if(_loc3_ >= 19968 && _loc3_ <= 40959)
            {
               return 1;
            }
            if(_loc3_ >= 32 && _loc3_ < 8704)
            {
               return -1;
            }
            _loc2_++;
         }
         return 0;
      }
      
      // 游戏是不是中文（判定依据：引擎推来的任务名本身就是本地化的）
      private function SaqUseChinese() : Boolean
      {
         if(this.SaqLangKnown)
         {
            return this.SaqLangZh;
         }
         if(this.QuestData != null)
         {
            var _loc1_:int = 0;
            while(_loc1_ < this.QuestData.length)
            {
               var _loc2_:Object = this.QuestData[_loc1_];
               var _loc3_:int = _loc2_ != null ? SaqNameVerdict(_loc2_.sName) : 0;
               if(_loc3_ != 0)
               {
                  this.SaqLangZh = _loc3_ > 0;
                  this.SaqLangKnown = true;
                  return this.SaqLangZh;
               }
               _loc1_++;
            }
         }
         return this.SaqLangZh;
      }
      
      // tab 标题。语言判出来之前先用**英文**（国际默认），QuestData 一到就会自我纠正
      // （PopulateTabs 里先建 tab，OnQuestDataUpdate 里再刷一次标题）。
      // 载荷里的 T 行是保留字段：语言未知时用它给的英文标题。
      private function SaqTabTitle() : String
      {
         if(this.SaqLangKnown)
         {
            return this.SaqLangZh ? SAQ_TITLE_ZH : SAQ_TITLE_EN;
         }
         if(this.SaqTitleEn != null && this.SaqTitleEn.length > 0)
         {
            return this.SaqTitleEn;
         }
         return SAQ_TITLE_EN;
      }
      
      private function SaqApplyTabTitle() : void
      {
         this.SetAvailableTabText(this.SaqTabTitle());
      }
      
      private function SaqEmbeddedPayload() : String
      {
         if(SAQ_EMBEDDED_CHUNKS == null || SAQ_EMBEDDED_CHUNKS.length == 0)
         {
            return null;
         }
         return SAQ_EMBEDDED_CHUNKS.join("");
      }
      
      // 解析载荷 -> 与语言无关的原始条目（名字中英都留着，取用时再按语言选）
      private function SaqParsePayload(param1:String) : Array
      {
         var _loc2_:Array = new Array();
         // ★ 第 36 轮：每次解析都从载荷重新确定「代理任务 FormID」——
         //   载荷换源（C++ 推送 ↔ 内嵌回退表）时不留下上一次的值。
         this.SaqProxyQuestID = 0;
         if(param1 == null)
         {
            return _loc2_;
         }
         var _loc3_:Array = param1.split("\n");
         var _loc4_:int = 0;
         while(_loc4_ < _loc3_.length)
         {
            var _loc5_:String = _loc3_[_loc4_];
            if(_loc5_.length > 2)
            {
               if(_loc5_.substr(0,2) == "T\t")
               {
                  var _loc6_:Array = _loc5_.substr(2).split("\t");
                  if(_loc6_.length > 0)
                  {
                     this.SaqTitleZh = _loc6_[0];
                     this.SaqTitleEn = _loc6_[_loc6_.length - 1];
                  }
               }
               else if(_loc5_.substr(0,2) == "P\t")
               {
                  // ★ 第 36 轮：P 行 = 代理任务（SAQ_MainQuest）的运行期 FormID。
                  //   ★ 第 44 轮起它只用于报告里的 `proxy=0x…`（诊断）；「设定航线」的
                  //   星图流程改由 Papyrus 脚本打开（第 44 轮删掉了原来的原版 dispatch，
                  //   见 SaqNoteStarMapHandoff 的说明）。旧载荷没有这一行 ⇒ 保持 0（不报错）。
                  var _loc8_:Number = Number(_loc5_.substr(2));
                  if(_loc8_ > 0)
                  {
                     this.SaqProxyQuestID = _loc8_;
                  }
               }
               else if(_loc5_.substr(0,2) == "Q\t")
               {
                  var _loc7_:Array = _loc5_.substr(2).split("\t");
                  if(_loc7_.length >= 3)
                  {
                     _loc2_.push({
                        "uID":parseInt(_loc7_[0]),
                        "iType":parseInt(_loc7_[1]),
                        "sNameZh":_loc7_[2],
                        "sNameEn":_loc7_.length >= 4 ? _loc7_[3] : _loc7_[2],
                        // ★ 第 23 轮：第 5 列 = 有没有引导目标（"1"/"0"）。
                        //   旧载荷缺这列时按 true（保持旧行为：点了由 DLL 判定）。
                        "bSaqHasTarget":_loc7_.length >= 5 ? _loc7_[4] == "1" : true,
                        // ★★ 第 46 轮（大项 B）：第 6 列 = 「全部候选都非常驻」
                        //   （远处一定取不到、必须靠近目标区域）—— 描述里提前告知玩家。
                        //   旧载荷 / 内嵌回退数据缺这列 ⇒ false（不提这回事）。
                        "bSaqNeedsApproach":_loc7_.length >= 6 ? _loc7_[5] == "1" : false,
                        // ★★ 第 65 轮（任务专属图标）：第 7 列 = 原版 UI 阵营枚举
                        //   （-1 = 无阵营；离线由 QUST 的 FTYP 关键字映射）。
                        //   旧载荷 / 旧内嵌数据缺这列 ⇒ NaN ⇒ SaqSafeFaction 折成 -1。
                        "iFaction":_loc7_.length >= 7 ? parseInt(_loc7_[6]) : FactionUtils.FACTION_NONE,
                        // ★★ 第 74 轮（同伴好感度任务）：第 8 列 = 「入口」同伴任务
                        //   （固定显示的那一类 —— 个人任务；"1"/"0"）。
                        //   描述里据此提示「需要与同伴的好感度达到一定水平后才能接取」；
                        //   旧载荷 / 旧内嵌数据缺这列 ⇒ false（不提这回事）。
                        "bSaqCompanion":_loc7_.length >= 8 ? _loc7_[7] == "1" : false,
                        // ★★ 第 75 轮（四大势力开头任务）：第 9/10 列 = 「简要说明」
                        //   （中 / 英；加入方式 / 前置条件；只有那四条非空）。
                        //   描述第一句用它（取代「这条任务当前可以接取」）；
                        //   旧载荷 / 旧内嵌数据缺这列 ⇒ 空串（走原来的文案）。
                        "sSaqNoteZh":_loc7_.length >= 9 ? _loc7_[8] : "",
                        "sSaqNoteEn":_loc7_.length >= 10 ? _loc7_[9] : "",
                        // ★★ 第 89 轮（可重复任务）：第 11 列 = 可重复标记（"1"/"0"）——
                        //   这类任务「做完一次还能再接」：FilterKnownQuests 对「已完成」的
                        //   条目**放行**（继续显示在「可接任务」里）。
                        //   旧载荷 / 旧内嵌数据缺这列 ⇒ false（老行为）。
                        "bSaqRepeatable":_loc7_.length >= 11 ? _loc7_[10] == "1" : false
                     });
                  }
               }
            }
            _loc4_++;
         }
         return _loc2_;
      }
      
      // 原始条目 -> 任务列表条目。
      //
      // 字段必须**覆盖引擎推的 QuestData 条目所拥有的一切**：UI 各处会直接读，
      // 少一个就可能抛 Error #1010（实测 MissionInfo.UpdateMissionInfo 会读
      // `param1.sDescription.length`，所以哪怕没有简介也必须给空串）。
      // 原始类型 -> UI 能安全渲染的类型（只折叠我们自己的扩展值）。
      //
      // ★★ 第 65 轮（任务专属图标）修订：原版图标 sprite（MissionVisuals.FactionSymbols.
      //   Icons_mc）实测解析出 13 帧 —— Activities / Misc / Missions / None + 9 个阵营帧
      //   （BlackFleet / FreestarCollective / HouseVaruun / RyujinIndustries / UnitedColonies /
      //    TrackersAlliance / Constellation / TerranArmada / Creations）。
      //   原版枚举 0..4 **全部**能安全 gotoAndStop（此前担心的「None 帧不存在」不成立），
      //   所以不再把派系(2)/主线(1) 归一成 4：真实类型 + 真实阵营 = 与原版任务菜单一致的图标。
      //   只有我们自己的扩展值（100 = 任务板入口 / 101 = 可重复 NPC 入口，见
      //   SAQ_ENTRY_TYPE / SAQ_REPEAT_NPC_TYPE）折叠回「任务」图标，保持入口条目既有视觉。
      private static function SaqSafeType(param1:int) : int
      {
         if(param1 == QuestUtils.ACTIVITY_QUEST_TYPE || param1 == QuestUtils.MAIN_QUEST_TYPE || param1 == QuestUtils.FACTION_QUEST_TYPE || param1 == QuestUtils.MISC_QUEST_TYPE || param1 == QuestUtils.MISSION_QUEST_TYPE)
         {
            return param1;
         }
         return QuestUtils.MISSION_QUEST_TYPE;
      }
      
      // ★★ 第 65 轮（任务专属图标）：阵营枚举的边界收敛。
      //   合法值 = -1（无阵营）或 0..9（FactionUtils 枚举顺序）；范围外 / NaN
      //   （旧载荷缺列时 parseInt 得到 NaN）⇒ 折成 -1（界面按 iType 选图标）。
      //   为什么要范围检查：这两个值会直接交给原版函数（GetQuestIconLabel 的
      //   gotoAndStop、MissionInfo.GetQuestColorIcon 的 getDefinitionByName）——
      //   「协议演进 / 数据串列」产生的越界值不应该带着疑问进原版代码。
      // ★★ 第 80 轮：入口条目的合并判据（任务板 100 / 可重复 NPC 101）——
      //   「按入口处理」的地方统一用它（子项名 / 描述 / 不可导航提示），
      //   防止以后再加入口类型时漏掉某一处（第 51/52 轮的教训：判断散落 = 漏改）。
      private static function SaqIsEntryType(param1:int) : Boolean
      {
         return param1 == SAQ_ENTRY_TYPE || param1 == SAQ_REPEAT_NPC_TYPE;
      }
      
      private static function SaqSafeFaction(param1:int) : int
      {
         if(param1 >= FactionUtils.FACTION_PARADISO && param1 <= FactionUtils.FACTION_CREATIONS)
         {
            return param1;
         }
         return FactionUtils.FACTION_NONE;
      }
      
      // 我们的条目带的「目标（阶段）」：一条静态文案。字段按 MissionsListEntry.SetEntryText /
      // ShowObjective 的读取清单给全（sName / iRemainingTime / bComplete / bActive /
      // bFailed / bIsMiscObjective / bCanShowOnMap）—— 少一个都可能渲染出问题。
      // 注意：**不能**带 aObjectives 属性（IsMission 的判据是 hasOwnProperty("aObjectives")，
      // 带了它这条子条目就会被当成"任务"）。
      private function SaqBuildObjective(param1:Object) : Object
      {
         return {
            "uID":param1.uID,
            "uOwnerQuestFormID":param1.uID,
            "uIndex":0,
            "uInstanceID":0,
            "iType":SaqSafeType(param1.iType),
            // 子项不是任务条目（无 aObjectives 的条目走 Objective 分支，不调用
            // SetFactionIcon）——阵营保持 -1，避免「子项也带势力徽记」这种原版没有的视觉。
            "iFaction":FactionUtils.FACTION_NONE,
            // ★ 第 27 轮：入口条目（任务板）的子项名不同 —— 它不是「任务」而是「入口」。
            // ★★ 第 80 轮：可重复 NPC（101）再单独一档 —— 它不是地点，是「人」。
            "sName":param1.iType == SAQ_REPEAT_NPC_TYPE
               ? (this.SaqUseChinese() ? "与他交谈（可重复任务）" : "Talk to them (repeatable job)")
               : (param1.iType == SAQ_ENTRY_TYPE
                  ? (this.SaqUseChinese() ? "前往任务板" : "Go to the mission board")
                  : (this.SaqUseChinese() ? "前往接取地点" : "Reach the pickup location")),
            "sDescription":"",
            "bComplete":false,
            "bFailed":false,
            "bActive":false,
            "bIsMiscObjective":false,
            "bCanShowOnMap":false,
            "iRemainingTime":-1,
            // ★ 第 14 轮：子项也带 SAQ 标记 —— 让 SaqIsOurEntry() 对主标题与子项**都**成立，
            //   交互才能与原版对齐（原版：点子项 = 追踪切换；点主标题 = 展开/收起）。
            "bSaqAvailable":true,
            // ★ 第 23 轮：子项也带上「能不能导航」——选中子项时按钮/拦截判据一致。
            "bSaqHasTarget":param1.bSaqHasTarget != false
         };
      }
      
      // 「设定航线」在当前控制映射下的键名（键盘 = R，手柄 = 手柄 X 键）；取不到返回 ""。
      // ★ 第 15 轮修正：不要写死键名 —— 事件名 "XButton" 是**手柄 X 按钮**，键盘下它映射到 R，
      //   写死「X 键」会让提示指向一个游戏里不存在的交互。
      private function SaqCourseKeyName() : String
      {
         var _loc1_:String = "";
         try
         {
            if(this.KeyHelper != null)
            {
               _loc1_ = this.KeyHelper.GetButtonNameForEvent("XButton","");
            }
         }
         catch(_loc2_:Error)
         {
            _loc1_ = "";
         }
         return _loc1_;
      }
      
      // ★★ 第 46 轮（大项 B）：这条任务的导航目标**只在靠近后才可用**（候选全是非常驻引用）
      //   —— 把原因写进描述，玩家点之前就知道（实测：远处点「营救机器人」⇒ 脚本取不到引用，
      //   旧行为是 19 秒后静默放弃，看起来像坏了）。判据来自 C++ 载荷第 6 列（见 SAQ.cpp
      //   的 AllCandidatesNonPersistent）；运行时另有 HUD 提示，见 SAQ_Main.psc。
      private function SaqApproachNote() : String
      {
         return this.SaqUseChinese()
            ? " 注意：它的导航目标要靠近目标区域后才加载 —— 距离较远时按「设定航线」可能暂时看不到标记（靠近后会自动生效）。"
            : " Note: its navigation target loads only when you are near its area - from a distance SET COURSE may show no marker at first (it starts automatically once you get closer).";
      }
      
      // ★★ 第 74 轮（同伴好感度任务）：这类任务**固定显示**（好感度没到也留在列表里），
      //   所以描述里不能再写「这条任务当前可以接取」（自相矛盾：好感度不够时玩家接不到）。
      //   首句换成「需要一定好感度才能接取」；判据 = C++ 载荷第 8 列（bSaqCompanion）。
      // ★★ 第 82 轮（文案说透 —— 玩家反馈「在好感度不够的情况下，这些引导意义何在」）：
      //   旧句「达到一定水平后才能接取」会让人以为要跑到某处「接取」——官方机制里
      //   根本没有这个环节：好感度里程碑一到，宿主脚本 `StartPersonalQuest()` 直接
      //   `PersonalQuest.Start()`（自动开始 + 弹一条帮助提示）；而好感度只能靠
      //   **带这位同伴一起冒险**来提升（StoryGate 计时器要求 companion following
      //   player，见 COM_CompanionQuestScript.psc）。所以引导指向的从来不是「接取
      //   地点」，而是**这位同伴本人当前所在的位置**（首选候选 = 同伴的常驻引用）。
      private function SaqCompanionNote() : String
      {
         return this.SaqUseChinese()
            ? "这条同伴任务会在你与这位同伴的好感度达到一定水平后自动开始，不需要找地方接取（在那之前它会一直显示在这里）。好感度要靠带这位同伴一起冒险来提升；「设定航线」引导到的是这位同伴当前所在的位置。"
            : "This companion quest starts automatically once your affinity with the companion is high enough - there is nothing to accept (it stays listed here until then). Affinity grows while the companion travels with you; SET COURSE leads to wherever the companion currently is.";
      }
      
      // ★★ 第 75 轮（四大势力开头任务）：其中「深红舰队」那条**没有导航目标**
      //   （数据侧故意清空了引导候选 —— 它的接取点在先锋队线两个任务之后才出现）。
      //   描述里要说清「按上面的说明推进」，而不是普通任务那句「暂时还没有导航目标」
      //   —— 后者听起来像 bug（玩家要求：不可引导也要有明确提示）。
      private function SaqNoPickupNote() : String
      {
         return this.SaqUseChinese()
            ? "它没有可以直接导航的接取地点 —— 按上面的说明推进即可。"
            : " There is no direct pickup location to navigate to - follow the note above.";
      }
      
      // ★★ 第 91 轮（不可导航提示更明显 —— 玩家反馈）：没有引导目标的条目
      //   （载荷第 5 列 bSaqHasTarget = false）在**列表名前面**加这个前缀。
      //
      //   为什么需要：此前「不可导航」只体现在右侧描述（第 23 轮）+ 点击后的提示
      //   （第 28 轮）—— 玩家在长列表里根本看不出来，点了没反应还是像 bug。
      //   现在名字本身带标记，不用选中就能一眼区分（与「（可重复）」前缀同一手法）。
      //   语言判定与描述文案同源（SaqUseChinese），中英各一条；英文带一个空格分隔。
      private function SaqNotNavigablePrefix() : String
      {
         return this.SaqUseChinese() ? "（不可导航）" : "(Not navigable) ";
      }
      
      // ★★ 第 96 轮（可重复任务分组 —— 玩家反馈）：可重复任务（载荷第 11 列
      //   bSaqRepeatable = true）在**列表名前面**加这个前缀（「（可重复）翻新商品」）。
      //
      //   为什么需要：这类任务做完一次还能再接（豁免「已完成」过滤 ⇒ 一直留在列表里），
      //   但此前「可重复」只写在**描述第一句**里 —— 玩家在长列表里扫一眼根本看不出来
      //   （与第 91 轮「（不可导航）」前缀同一手法：名字本身带标记，不用选中就能区分）。
      //   前缀与第 80 轮的「（可重复）NPC」入口条目同名同形（玩家要求「一样」）。
      //   语言判定与描述文案同源（SaqUseChinese），中英各一条；英文带一个空格分隔。
      private function SaqRepeatablePrefix() : String
      {
         return this.SaqUseChinese() ? "（可重复）" : "(Repeatable) ";
      }
      
      // 右侧详情面板里的描述文案（固定内容，告诉玩家这条记录怎么用）。
      // ★ 第 27 轮：第 2 个参数 = 条目类型（100 = 入口任务板）—— 它没有「接取地点」
      //   的概念，描述改成「这是什么、怎么去」。
      //   ★★ 第 80 轮：改传**完整 iType**（不再传 Boolean）—— 101 = 可重复 NPC 也要
      //   走入口分支（文案不同），用 SaqIsEntryType() 判定。
      // ★ 第 46 轮：第 3 个参数 = 需要靠近（见 SaqApproachNote）。
      // ★★ 第 74 轮：第 4 个参数 = 「入口」同伴任务（见 SaqCompanionNote）。
      // ★★ 第 75 轮：第 5 个参数 = 「简要说明」（四大势力开头任务；载荷第 9/10 列，
      //   空串 = 普通任务）—— 非空时它直接当描述第一句（「加入方式 / 前置条件」），
      //   取代「这条任务当前可以接取」（对固定显示的那四条不成立）。
      private function SaqDescriptionText(param1:Boolean, param2:int = 0, param3:Boolean = false, param4:Boolean = false, param5:String = "") : String
      {
         // ★ 第 27 轮：无限任务入口（任务板）。
         // ★★ 第 80 轮：可重复 NPC（101）—— 同属入口（uID 也是世界引用），文案另写。
         // ★ 第 29 轮：入口引用已经在 ESM 里 override 成**常驻引用**（任何位置都能取到），
         //   所以这个「取不到」分支只是兜底（ESM 没加载 / 被别的插件覆盖掉时）。
         //   措辞不再提「太远」——玩家明确反馈「不该存在太远就不能导航」。
         if(SaqIsEntryType(param2))
         {
            if(param1 != true)
            {
               return this.SaqUseChinese()
                  ? "暂时无法导航 —— 这个位置此刻取不到（多半是所在区域还没加载出来）。稍后重新打开一次任务菜单再试。"
                  : "Cannot navigate right now - the location is not available at the moment (its area has not loaded yet). Reopen the mission menu and try again.";
            }
            if(param2 == SAQ_REPEAT_NPC_TYPE)
            {
               if(this.SaqCourseKeyName().length == 0)
               {
                  return this.SaqUseChinese()
                     ? "这位 NPC 会不断提供可重复任务 —— 与他交谈就能接到赏金、运输、勘探等不断刷新的任务。使用底部的「设定航线」即可引导到他的位置。"
                     : "This NPC offers repeatable jobs - talk to them to pick up endlessly refreshing missions (bounties, transport, survey...). Use SET COURSE to be guided to their location.";
               }
               return this.SaqUseChinese()
                  ? "这位 NPC 会不断提供可重复任务 —— 与他交谈就能接到赏金、运输、勘探等不断刷新的任务。按 " + this.SaqCourseKeyName() + "（设定航线）即可引导到他的位置。"
                  : "This NPC offers repeatable jobs - talk to them to pick up endlessly refreshing missions (bounties, transport, survey...). Press " + this.SaqCourseKeyName() + " (SET COURSE) to be guided to their location.";
            }
            if(this.SaqCourseKeyName().length == 0)
            {
               return this.SaqUseChinese()
                  ? "这是一块任务板 —— 与它交互就能接到赏金、运输、勘探等不断刷新的任务。使用底部的「设定航线」即可引导到它的位置。"
                  : "This is a mission board - interact with it to pick up endlessly refreshing jobs (bounties, transport, survey...). Use SET COURSE to be guided to its location.";
            }
            return this.SaqUseChinese()
               ? "这是一块任务板 —— 与它交互就能接到赏金、运输、勘探等不断刷新的任务。按 " + this.SaqCourseKeyName() + "（设定航线）即可引导到它的位置。"
               : "This is a mission board - interact with it to pick up endlessly refreshing jobs (bounties, transport, survey...). Press " + this.SaqCourseKeyName() + " (SET COURSE) to be guided to its location.";
         }
         // ★★ 第 74 轮：首句分两种 —— 普通任务「当前可以接取」；「入口」同伴任务
         //   「需要好感度达标后才能接取」（param4 = bSaqCompanion，见 SaqCompanionNote）。
         // ★★ 第 75 轮：势力开头任务的「简要说明」（param5）最优先 —— 它已经写清
         //   加入方式 / 前置条件，不能再接「当前可以接取」那句。
         var _loc1_:String;
         if(param5.length > 0)
         {
            _loc1_ = param5;
         }
         else if(param4 == true)
         {
            _loc1_ = this.SaqCompanionNote();
         }
         else
         {
            _loc1_ = this.SaqUseChinese() ? "这条任务当前可以接取。" : "This quest is currently available.";
         }
         // ★ 第 46 轮：全是非常驻候选的任务追加一句「需要靠近」（param3 = bSaqNeedsApproach）
         var _loc2_:String = param3 == true ? this.SaqApproachNote() : "";
         // ★ 第 23 轮：没有引导目标的任务（261 条里 52 条）——列表照常显示，但**无法导航**。
         //   把原因直接写进描述，玩家不用点一下才知道（此前「点了瞬间回滚」看不出原因）。
         //   ★★ 第 75 轮：势力开头任务里「按设计不给导航」的那条（深红舰队）另写一句
         //   （见 SaqNoPickupNote）—— 它缺导航目标不是「还没准备好」而是**故意**的。
         if(param1 != true)
         {
            if(param5.length > 0)
            {
               return _loc1_ + this.SaqNoPickupNote() + _loc2_;
            }
            // ★★ 第 82 轮：同伴条目的「无目标」兜底也换落点说法（见 SaqCompanionNote）。
            if(param4 == true)
            {
               return _loc1_ + (this.SaqUseChinese()
                  ? "但它暂时还没有导航目标 —— 无法引导到这位同伴的位置（条目照常显示）。"
                  : " It has no navigation target yet, so it cannot guide you to the companion's location (the entry stays listed).") + _loc2_;
            }
            return _loc1_ + (this.SaqUseChinese()
               ? "但它暂时还没有导航目标 —— 无法引导到接取地点（任务本身照常显示）。"
               : " It has no navigation target yet, so it cannot guide you to the pickup location.") + _loc2_;
         }
         var _loc3_:String = this.SaqCourseKeyName();
         // ★★ 第 82 轮：同伴条目的落点不是「接取地点」而是**这位同伴本人** ——
         //   尾部文案跟着换，否则与首句（SaqCompanionNote）自相矛盾。
         if(param4 == true)
         {
            if(_loc3_.length == 0)
            {
               return _loc1_ + (this.SaqUseChinese()
                  ? "使用底部的「设定航线」即可引导到这位同伴的位置。"
                  : " Use SET COURSE to be guided to the companion's location.") + _loc2_;
            }
            return _loc1_ + (this.SaqUseChinese()
               ? "按 " + _loc3_ + "（设定航线）即可引导到这位同伴的位置。"
               : " Press " + _loc3_ + " (SET COURSE) to be guided to the companion's location.") + _loc2_;
         }
         if(_loc3_.length == 0)
         {
            return _loc1_ + (this.SaqUseChinese()
               ? "展开后选中目标，或使用底部的「设定航线」即可引导到接取地点。"
               : " Expand it, then select the objective or use SET COURSE to be guided to the pickup location.") + _loc2_;
         }
         return _loc1_ + (this.SaqUseChinese()
            ? "展开后选中目标，或按 " + _loc3_ + "（设定航线）即可引导到接取地点。"
            : " Expand it, then select the objective or press " + _loc3_ + " (SET COURSE) to be guided to the pickup location.") + _loc2_;
      }
      
      // ★★ 第 75 轮（四大势力开头任务）：「简要说明」真的进了描述 —— 报告里报出
      //   **第一条带说明的条目**的 `<uID>=<描述前 24 字>`（最多一条）。
      //   为什么需要：数据列写对了 ≠ 描述里真的用了它（与 `order=` / `icon=` 探针同一思路：
      //   整条链路 data → 载荷 → 解析 → sDescription 只靠读代码保证）——harness 用例
      //   的判据也用它（`assert.ui pin=[0x2c5401=加入联合殖民地先锋队…`）。
      //   只报一条 + 截 24 字：报告有长度上限（C++ 侧按 900 字转义落盘），别把别的字段挤掉。
      private function SaqPinNoteProbe() : String
      {
         try
         {
            if(this.AvailableQuests == null)
            {
               return "";
            }
            var _loc1_:int = 0;
            while(_loc1_ < this.AvailableQuests.length)
            {
               var _loc2_:Object = this.AvailableQuests[_loc1_];
               if(_loc2_ != null && _loc2_.sSaqNote != null && _loc2_.sSaqNote.length > 0)
               {
                  var _loc3_:String = _loc2_.sDescription;
                  if(_loc3_ == null)
                  {
                     _loc3_ = "";
                  }
                  if(_loc3_.length > 24)
                  {
                     _loc3_ = _loc3_.substr(0,24);
                  }
                  return "0x" + Number(_loc2_.uID).toString(16) + "=" + _loc3_;
               }
               _loc1_++;
            }
         }
         catch(e:Error)
         {
            return "(ex)";
         }
         return "";
      }
      
      // ★★ 第 80 轮（可重复 NPC 入口）：报告里报出「可重复 NPC 条目」的**计数 + 前 2 条 uID**
      //   （短格式，例：`rep=[8|0x214684=（可重复）贸易管理局 · 邓肯·林奇,0x115442]`
      //   —— 第一条带名字，用例据此断言「（可重复）」前缀真的进了载荷）。
      //   为什么需要：C++ 静态表 8 条（type=101）⇒ 载荷 ⇒ 界面解析 ⇒ `SaqRawQuests`
      //   里真的存在这些条目 ——「数据对了 ≠ 界面拿到了」这条链路只靠读代码保证
      //   （与 order= / pin= 探针同一思路）。
      //   用 SaqRawQuests（**未折叠 iType** 的原始解析结果）：AvailableQuests 里的
      //   iType 已被 SaqSafeType 折成原版枚举，认不出 101。
      private function SaqRepeatNpcProbe() : String
      {
         try
         {
            if(this.SaqRawQuests == null)
            {
               return "";
            }
            var _loc1_:int = 0;
            var _loc2_:Array = new Array();
            var _loc3_:int = 0;
            while(_loc3_ < this.SaqRawQuests.length)
            {
               var _loc4_:Object = this.SaqRawQuests[_loc3_];
               if(_loc4_ != null && int(_loc4_.iType) == SAQ_REPEAT_NPC_TYPE)
               {
                  _loc1_++;
                  if(_loc2_.length < 2)
                  {
                     var _loc5_:String = this.SaqUseChinese() ? _loc4_.sNameZh : _loc4_.sNameEn;
                     if(_loc5_ == null)
                     {
                        _loc5_ = "";
                     }
                     if(_loc2_.length == 0)
                     {
                        if(_loc5_.length > 24)
                        {
                           _loc5_ = _loc5_.substr(0,24);
                        }
                        _loc2_.push("0x" + Number(_loc4_.uID).toString(16) + "=" + _loc5_);
                     }
                     else
                     {
                        _loc2_.push("0x" + Number(_loc4_.uID).toString(16));
                     }
                  }
               }
               _loc3_++;
            }
            return _loc1_ + "|" + _loc2_.join(",");
         }
         catch(e:Error)
         {
            return "(ex)";
         }
      }
      
      // ★★ 第 91 轮（不可导航提示更明显）：报告里报出**不可导航条目**的计数 + 前 2 条的
      //   `<uID>=<显示名>`（例：`nonav=[3|0x994a=（不可导航）伦敦地标任务,…]`）。
      //
      //   为什么需要：前缀加在 SaqBuildEntry 的 sName 上，而 sName 正是
      //   MissionsListEntry.SetEntryText 渲染的那个字段 ——「代码里有前缀」与
      //   「列表里真的显示前缀」中间隔着载荷解析 + 条目构建两层，只靠读代码保证；
      //   本探针给出**运行期显示名**，harness 用例据此断言（与 order= / pin= / rep= 同思路）。
      //   只报 2 条 + 名字截 24 字：报告有长度上限，别把 qdata 那类专业证据挤掉。
      private function SaqNotNavigableProbe() : String
      {
         try
         {
            if(this.AvailableQuests == null)
            {
               return "";
            }
            var _loc1_:int = 0;
            var _loc2_:Array = new Array();
            var _loc3_:int = 0;
            while(_loc3_ < this.AvailableQuests.length)
            {
               var _loc4_:Object = this.AvailableQuests[_loc3_];
               if(_loc4_ != null && _loc4_.bSaqHasTarget != true)
               {
                  _loc1_++;
                  if(_loc2_.length < 2)
                  {
                     var _loc5_:String = _loc4_.sName != null ? String(_loc4_.sName) : "";
                     if(_loc5_.length > 24)
                     {
                        _loc5_ = _loc5_.substr(0,24);
                     }
                     _loc2_.push("0x" + Number(_loc4_.uID).toString(16) + "=" + _loc5_);
                  }
               }
               _loc3_++;
            }
            return _loc1_ + "|" + _loc2_.join(",");
         }
         catch(e:Error)
         {
            return "(ex)";
         }
      }
      
      // ★★ 第 96 轮（可重复任务分组）：报告里报出**可重复任务**的计数 + 前 2 条的
      //   `<uID>=<显示名>`（例：`rq=[20|0x224fe8=（可重复）翻新商品,0x…]`）。
      //
      //   为什么需要：前缀加在 SaqBuildEntry 的 sName 上 ——「代码里有前缀」与
      //   「列表里真的显示前缀」中间隔着载荷解析 + 条目构建两层，只靠读代码保证；
      //   本探针给出**运行期显示名**（sName = MissionsListEntry.SetEntryText 渲染的
      //   字段），harness 用例据此断言（与 order= / nonav= 探针同一思路）。
      //   ★ 分组（整组排列表末尾）的运行期证据在 `order=` 的 `|tail=` 段（MissionsList.
      //     SAQ_OrderProbe 报本 tab 最后两行的显示名）。
      //   只报 2 条 + 名字截 24 字：报告有长度上限，别把 qdata 那类专业证据挤掉。
      private function SaqRepeatableQuestProbe() : String
      {
         try
         {
            if(this.AvailableQuests == null)
            {
               return "";
            }
            var _loc1_:int = 0;
            var _loc2_:Array = new Array();
            var _loc3_:int = 0;
            while(_loc3_ < this.AvailableQuests.length)
            {
               var _loc4_:Object = this.AvailableQuests[_loc3_];
               if(_loc4_ != null && _loc4_.bSaqRepeatable == true)
               {
                  _loc1_++;
                  if(_loc2_.length < 2)
                  {
                     var _loc5_:String = _loc4_.sName != null ? String(_loc4_.sName) : "";
                     if(_loc5_.length > 24)
                     {
                        _loc5_ = _loc5_.substr(0,24);
                     }
                     _loc2_.push("0x" + Number(_loc4_.uID).toString(16) + "=" + _loc5_);
                  }
               }
               _loc3_++;
            }
            return _loc1_ + "|" + _loc2_.join(",");
         }
         catch(e:Error)
         {
            return "(ex)";
         }
      }
      
      private function SaqBuildEntry(param1:Object) : Object
      {
         // ★★ 第 75 轮：势力开头任务的「简要说明」（按语言挑；空串 = 普通任务）。
         //   先取出来算一次：描述与报告探针（SAQ_Report 的 pin= 字段）都用它。
         var _loc1_:String = this.SaqUseChinese() ? param1.sSaqNoteZh : param1.sSaqNoteEn;
         if(_loc1_ == null)
         {
            _loc1_ = "";
         }
         // ★★ 第 91 轮（不可导航提示更明显）：显示名 = 原名（+ 不可导航前缀）。
         //   前缀只加在**不可导航**的条目上（载荷第 5 列 bSaqHasTarget = false ⇒
         //   这条点了不会有导航）—— 见 SaqNotNavigablePrefix。
         //   原名另存 sSaqBaseName：提示（「该任务暂无导航目标:…」）与日志探针报它，
         //   否则会出现「该任务暂无导航目标:（不可导航）X」这种废话，也会打乱既有用例。
         // ★★ 第 96 轮（可重复任务分组）：显示名**前面**再加「（可重复）」——
         //   可重复任务（载荷第 11 列 bSaqRepeatable = true）做完一次还能再接（一直留在
         //   列表里），名字本身带标记才好在长列表里一眼认出来（见 SaqRepeatablePrefix）。
         //   两个前缀的次序：可重复在前、不可导航在后（「（可重复）（不可导航）危险材料」）。
         //   入口条目（type 100/101）不带 bSaqRepeatable ⇒ 「（可重复）NPC」入口的字样
         //   仍来自载荷名字，**不会**被加第二遍。
         var _loc2_:String = this.SaqUseChinese() ? param1.sNameZh : param1.sNameEn;
         if(_loc2_ == null)
         {
            _loc2_ = "";
         }
         var _loc3_:Boolean = param1.bSaqHasTarget == false;
         var _loc4_:Boolean = param1.bSaqRepeatable == true;
         var _loc5_:String = (_loc4_ ? this.SaqRepeatablePrefix() : "")
            + (_loc3_ ? this.SaqNotNavigablePrefix() : "");
         return {
            "uID":param1.uID,
            "uInstanceID":0,
            "iType":SaqSafeType(param1.iType),
            // ★★ 第 65 轮（任务专属图标）：真实阵营（-1 = 无阵营）—— 列表图标
            //   （MissionsListEntry.SetFactionIcon → GetQuestIconLabel）与右侧详情面板
            //   的阵营名 / 彩色图标（MissionInfo → FactionUtils.GetFactionName /
            //   GetQuestColorIcon）都用它，显示效果与原版任务菜单一致。
            "iFaction":SaqSafeFaction(param1.iFaction),
            "sName":_loc5_.length > 0 ? _loc5_ + _loc2_ : _loc2_,
            // ★★ 第 91 轮：不带前缀的原名（提示 / 探针用，见 SaqBaseName）。
            //   ★★ 第 96 轮：可重复前缀同样不带进这里 —— 提示/日志仍报「翻新商品」。
            "sSaqBaseName":_loc2_,
            // ★ 第 27 轮：入口条目（任务板）的描述用专门文案（第 2 个参数）。
            // ★★ 第 74 轮：第 4 个参数 = 「入口」同伴任务（描述里提示好感度要求）。
            // ★★ 第 75 轮：第 5 个参数 = 势力开头任务的「简要说明」（上面取好的 _loc1_）。
            // ★★ 第 80 轮：第 2 个参数改传**完整 iType**（100 = 任务板 / 101 = 可重复 NPC，
            //   见 SaqDescriptionText 与 SaqIsEntryType）。
            "sDescription":this.SaqDescriptionText(param1.bSaqHasTarget != false, param1.iType, param1.bSaqNeedsApproach == true, param1.bSaqCompanion == true, _loc1_),
            // ★★ 第 75 轮：把说明留在条目上 —— SAQ_Report 的 pin= 探针据此报出
            //   「说明真的进了描述」（数据列对了 ≠ 描述里真的用了它）。
            "sSaqNote":_loc1_,
            // ★★ 第 89 轮（可重复任务）：可重复标记（载荷第 11 列）—— FilterKnownQuests
            //   据此豁免「在玩家日志里」的丢弃（已完成 + 可重复 ⇒ 保留；进行中照旧隐藏）。
            "bSaqRepeatable":param1.bSaqRepeatable == true,
            // 引导中的那条保持「追踪中」的视觉（左侧竖条）—— 列表重建（SaqRefresh）后不丢状态。
            "bActive":this.SaqGuideQuest != 0 && param1.uID == this.SaqGuideQuest,
            "bComplete":false,
            "bFailed":false,
            "bCanBeRejected":false,
            "bIsMiscQuest":false,
            "bIsMiscObjective":false,
            "bCanShowOnMap":false,
            "iRemainingTime":-1,
            // ★ 第 12 轮：带一条「目标（阶段）」——玩家反馈「看不到任务阶段，没法像原版
            //   任务那样展开看内容」。原版 MissionsList 展开子条目 = aObjectives
            //   （见 MissionsList.GetChildrenOfEntry），空数组时条目就是个没有阶段的死条目。
            "aObjectives":[this.SaqBuildObjective(param1)],
            // ★ 可见性标记（MissionsList.EntryFilterCompare_Impl 里唯一认它的判据）：
            //   iType 保留原始任务类型给图标/类型文本用，**不能**再靠 iType 决定
            //   是否出现在「可接任务」tab（那是上一轮列表空的根因）。
            "bSaqAvailable":true,
            // ★ 第 23 轮：能不能导航（SET COURSE 按钮置灰 / 点击拦截都用它）
            "bSaqHasTarget":param1.bSaqHasTarget != false
         };
      }
      
      // 解析 + 建条目 + 过滤掉玩家已知任务 + 合并进任务列表 + 刷新 tab 标题
      private function SaqRefresh() : int
      {
         if(this.SaqRawQuests == null)
         {
            var _loc1_:String = this.SaqSourceIsCpp ? this.SaqSourcePayload : this.SaqEmbeddedPayload();
            this.SaqRawQuests = this.SaqParsePayload(_loc1_);
         }
         var _loc2_:Array = new Array();
         var _loc3_:int = 0;
         while(_loc3_ < this.SaqRawQuests.length)
         {
            _loc2_.push(this.SaqBuildEntry(this.SaqRawQuests[_loc3_]));
            _loc3_++;
         }
         this.RawAvailableQuests = _loc2_;
         this.AvailableQuests = this.FilterKnownQuests(_loc2_);
         this.SaqAutoCancelIfAccepted();
         this.SaqApplyTabTitle();
         if(this.MissionsList_mc != null)
         {
            // 把列表掩码与本菜单当前选中的 tab 对齐一次。
            // （BSScrollingTree 的默认掩码是 0xFFFFFFFF；如果这一帧还没人设置过它，
            //   「全部」tab 会用 0xFFFFFFFF 放行 bSaqAvailable 条目的判据 —— 这里先对齐，
            //   保证重建列表时用的是当前 tab 的真实掩码。）
            this.SaqSyncListMask();
            this.MissionsList_mc.InitializeEntries(this.BuildMergedList());
            this.SaqSnapshotTab("refresh");
            if(this.visible)
            {
               this.onMissionSelectionChange();
            }
         }
         return _loc2_.length;
      }
      
      private function SaqSyncListMask() : void
      {
         var _loc1_:int = this.TabbedFilterSelection_mc != null ? int(this.TabbedFilterSelection_mc.selectedIndex) : -1;
         if(_loc1_ >= 0 && _loc1_ < this.FilterInfoA.length)
         {
            this.MissionsList_mc.filterMask = this.FilterInfoA[_loc1_].flag;
         }
      }
      
      // 界面快照（第 9 轮）：在「切 tab」和「重建列表」这两个时刻记下
      // 「tab 序号 / 掩码 / 当前列表条数」。
      //
      // 为什么要有它：C++ 侧只能在推送那一刻读一次 SAQ_Report，而那时玩家还没切到
      // 我们那个 tab（实测 tab=0、mask=0xFFFFFFBF）—— 于是「我们 tab 里到底有几条」
      // 在日志里始终是空白。加上这个快照后，只要玩家**碰过**我们那个 tab，
      // 无论他之后切到哪里，SAQ_Report 都会把那一刻的状态带出来。
      private function SaqSnapshotTab(param1:String) : void
      {
         if(this.MissionsList_mc == null || this.TabbedFilterSelection_mc == null || this.FilterInfoA == null)
         {
            return;
         }
         var _loc2_:int = int(this.TabbedFilterSelection_mc.selectedIndex);
         var _loc3_:int = int(this.MissionsList_mc.filterMask);
         var _loc4_:int = int(this.MissionsList_mc.entryCount);
         var _loc5_:String = "tab=" + _loc2_ + " mask=0x" + (_loc3_ >>> 0).toString(16) + " list=" + _loc4_;
         this.SaqTabProbe = param1 + "[" + _loc5_ + "]";
         if(_loc2_ == this.FilterInfoA.length - 1)
         {
            this.SaqOurTabProbe = _loc5_;
            if(_loc4_ > this.SaqOurTabMaxList)
            {
               this.SaqOurTabMaxList = _loc4_;
            }
         }
      }
      
      // ==================================================================
      //  把 SAQ 入口挂到 SWF 的 root 上 —— 这是 C++ 推送能用起来的关键。
      //
      //  背景：C++ 侧只能通过 ASMovieRoot::Invoke("A.B.C") 调 AS3，而路径解析
      //  **从 root 开始**。MissionMenu 这个类（Embed 自 assets.swf 的 symbol94）
      //  是主时间轴上的**子元件**，不是 root 本身，所以
      //  "SetAvailableQuests" / "_root.SetAvailableQuests" / "_root.root.…"
      //  在 root 上都找不到 —— 日志里就是六种组合全 fail。
      //  在 root（MainTimeline，dynamic 的 MovieClip）上挂一份函数引用后，
      //  C++ 调 "SAQ_SetAvailableQuests" 就能直达本实例。
      // ==================================================================
      private function SaqPublishEntryPoint() : void
      {
         try
         {
            var _loc1_:Object = this.root;
            if(_loc1_ != null && _loc1_ != this)
            {
               _loc1_["SAQ_SetAvailableQuests"] = this.SetAvailableQuests;
               _loc1_["SAQ_Probe"] = this.SAQ_Probe;
               _loc1_["SAQ_ApplyPayload"] = this.SAQ_ApplyPayload;
               _loc1_["SAQ_Report"] = this.SAQ_Report;
               _loc1_["SAQ_PeekGuide"] = this.SAQ_PeekGuide;
               // ★ 第 16 轮：C++ → 界面的两条回写通道
               //   SAQ_GuideReply     = 引导请求的处理结果（成功/没有引导目标/写失败）
               //   SAQ_SyncGuideState = 菜单打开后同步「当前实际引导任务」
               _loc1_["SAQ_GuideReply"] = this.SAQ_GuideReply;
               _loc1_["SAQ_SyncGuideState"] = this.SAQ_SyncGuideState;
               // ★★ 第 49 轮补丁③（首测 + 复测复查）：**测试驱动入口也必须挂在这里**。
               //   第 49 轮只把 SAQ_TestDrive* 加进了类里 —— 而 C++ 只能调 `_root.xxx`
               //   （本函数上方的背景说明），于是 `_root.SAQ_TestDriveTab` 在 root 上
               //   根本不存在 ⇒ Invoke 0 ms 失败（`fail(路径不存在或调用失败)`）。
               //   两轮实测的失败形态完全一样（0 ms）—— 与参数个数无关：
               //   `SAQ_Report`（挂了的）0 参调用一直成功，`SAQ_TestDriveTab`（没挂的）
               //   用 0 参也照样失败。教训：**加了新入口，必须同时加到这份清单里**。
               _loc1_["SAQ_TestDriveTab"] = this.SAQ_TestDriveTab;
               _loc1_["SAQ_TestDriveSelect"] = this.SAQ_TestDriveSelect;
               // ★ 第 54 轮：子项选中（Enter 的「只引导」路径 —— 主标题的 Enter 只展开）
               _loc1_["SAQ_TestDriveSelectChild"] = this.SAQ_TestDriveSelectChild;
               _loc1_["SAQ_TestDriveExpand"] = this.SAQ_TestDriveExpand;
               _loc1_["SAQ_TestDriveKey"] = this.SAQ_TestDriveKey;
               _loc1_["SAQ_TestDriveState"] = this.SAQ_TestDriveState;
               // ★ 第 51 轮：记录挂载结果 —— SAQ_Report 的 ep= 自检字段据此定性：
               //   挂载代码没跑到（not-run）/ root 取不到（no-root）/ 抛异常（ex:…）/
               //   挂载完成（ok，此时若 root 上仍取不到入口，就是另一层的问题）。
               this.SaqPublishNote = "ok";
               }
            else
            {
               this.SaqPublishNote = "no-root";
            }
         }
         catch(e:Error)
         {
            this.SaqPublishNote = "ex:" + e.message;
         }
      }
      
      // C++ 插件入口：Invoke("SetAvailableQuests", <载荷>)。
      // 返回值约定（C++ 侧据此判断协议有没有通）：
      //   >0  = 解析成功（值是解析到的条数）
      //   -1  = 参数是 null/空串（★ 参数没传过来 / 传成空）
      //   -2  = 参数非空但解析不出条目（编码/格式问题）★ 此时自动回退内嵌表
      // 返回「解析出来的」条数而不是过滤后的数量：一旦任务全被 QuestData 滤掉就成 0，
      // C++ 会误判「协议没通」，白试剩下几种组合。
      public function SetAvailableQuests(param1:String) : int
      {
         if(param1 == null || param1.length == 0)
         {
            return -1;
         }
         this.SaqSourcePayload = param1;
         this.SaqSourceIsCpp = true;
         this.SaqRawQuests = null;
         var _loc2_:int = this.SaqRefresh();
         if(_loc2_ <= 0)
         {
            this.SaqSourceIsCpp = false;
            this.SaqRawQuests = null;
            this.SaqRefresh();
            return -2;
         }
         return _loc2_;
      }
      
      // C++ 诊断入口：把收到的字符串长度 + 前缀原样返回。
      // 用途：Invoke 的参数如果没传对（编码/截断/NUL），这条一眼能看出来。
      public function SAQ_Probe(param1:String) : String
      {
         if(param1 == null)
         {
            return "null";
         }
         return param1.length + "|" + param1.substr(0,24);
      }
      
      // C++ 备用入口（SetVariable 通路）：载荷先放到 root 的 SAQ_Payload 变量上，
      // 这里无参调用 —— 绕开「Invoke 带参数」这条链路的潜在问题。
      public function SAQ_ApplyPayload() : int
      {
         var _loc1_:* = this.root["SAQ_Payload"];
         if(_loc1_ == null)
         {
            return -1;
         }
         return this.SetAvailableQuests(String(_loc1_));
      }
      
      // C++ 诊断入口（**只读**，不改任何状态）：把本实例当前的关键状态回读成一行字符串。
      //
      // 为什么需要它：第 7 轮实测日志里「推送成功 + 返回 0」，靠日志**无法判断**
      // 界面到底有没有按推送的数据渲染（返回 0 其实是 C++ 读 int 的方式错了），
      // 只能靠肉眼看游戏 —— 这一条把这个缺口补上：日志里直接给出
      //   「解析到几条 / 过滤后剩几条 / 列表里几条 / 当前掩码 / 选中 tab / 语言 / 标题」。
      //
      // 字段含义：
      //   src       = 数据源（cpp = C++ 推送；embedded = SWF 内嵌回退表）
      //   raw       = 载荷解析出的条数（-1 = 还没解析过）
      //   keep      = 滤掉「玩家已知任务」后剩下的条数（-1 = 空）
      //   questData = 引擎推给 UI 的任务条数（语言判定与已知任务过滤都靠它）
      //   list      = 列表当前实际条目数（含引擎推的任务 + 我们的条目）
      //   mask      = 列表当前过滤掩码（我们 tab 应该是 0x40）
      //   tab       = 当前选中的 tab 序号（我们的是最后一个 = 7）
      //   lang      = 语言判定结果
      //   title     = 我们那个 tab 此刻的标题
      //   last      = 最近一次「切 tab / 重建列表」时的界面快照（第 9 轮）
      //   ourTab    = 我们那个 tab 被选中时的最后一次快照（没碰过就是 "-"）
      //   ourTabMax = 我们那个 tab 上见过的最大条目数（-1 = 没碰过）
      public function SAQ_Report() : String
      {
         var _loc1_:int = this.SaqRawQuests != null ? this.SaqRawQuests.length : -1;
         var _loc2_:int = this.AvailableQuests != null ? this.AvailableQuests.length : -1;
         var _loc3_:int = this.QuestData != null ? this.QuestData.length : -1;
         var _loc4_:int = this.MissionsList_mc != null ? int(this.MissionsList_mc.entryCount) : -1;
         var _loc5_:int = this.MissionsList_mc != null ? int(this.MissionsList_mc.filterMask) : -1;
         var _loc6_:int = this.TabbedFilterSelection_mc != null ? int(this.TabbedFilterSelection_mc.selectedIndex) : -1;
         var _loc7_:String = this.SaqLangKnown ? (this.SaqLangZh ? "zh" : "en") : "?";
         // ★ 掩码按**无符号**十六进制打（第 8 轮实测打出来是 `0x-41`，即 -0x41 = 0xFFFFFFBF，
         //   看日志的人得自己心算补码；>>> 0 转成 uint 后就是 0xffffffbf）。
         var _loc8_:String = "src=" + (this.SaqSourceIsCpp ? "cpp" : "embedded")
            + " raw=" + _loc1_
            + " keep=" + _loc2_
            + " questData=" + _loc3_
            + " list=" + _loc4_
            + " mask=0x" + (_loc5_ >>> 0).toString(16);
         _loc8_ += " tab=" + _loc6_
            + " lang=" + _loc7_
            + " title=" + this.SaqTabTitle()
            + " visible=" + (this.visible ? "1" : "0");
         // ★★ 第 50 轮：SWF 构建指纹（诊断用）。
         //   起因：第 49 轮补丁③（测试入口挂到 root）部署 + 字节码级验证（FFDec P-code）
         //   都证明 SWF 是对的，而 22:48 会话的 `ui.tab` 仍 0 ms 失败 —— 证据链指向
         //   「游戏加载的仍是部署前的旧 SWF」：Starfield 的 UI 资源在**游戏启动阶段**
         //   加载（早于 SFSE 插件加载日志的时刻），而补丁③是在游戏进程启动之后才部署的。
         //   指纹写进本报告 ⇒ 日志里一眼看出游戏加载的是哪一版 SWF：
         //     有 `stamp=50` = 本次构建；没有 = 旧版（**完全重启游戏**后才会更新）。
         //   ★ 以后每改一次 SWF，就把这个数字 +1（verify 检查 `stamp=` 是否存在）。
         //   ★ 第 65 轮（任务专属图标）：stamp 54 —— 载荷加第 7 列（阵营），
         //     列表图标改为与原版一致（真实 iType + iFaction）。
         //   ★★ 第 74 轮（同伴好感度任务）：载荷加第 8 列（同伴固定显示），描述里提示
         //     「需要一定好感度才能接取」（见 SaqCompanionNote）。
         //   ★★ 第 74 轮续（同伴任务分组）：stamp 56 —— 新增 `order=` 顺序探针
         //     （同伴任务前置 + 按同伴分组的运行期证据，见 MissionsList.SAQ_OrderProbe）。
         //     ★ 为什么同轮再 +1：SWF 在**游戏启动阶段**加载，「部署了但游戏没重启」
         //     时必须能区分「加载的是哪一版」—— 部署前若已跑过 stamp=55 的那份，
         //     只有升到 56 才能定性。
         //   ★★ 第 75 轮（四大势力开头任务）：stamp 57 —— 载荷加第 9/10 列（简要说明）+
         //     描述第一句改为「简要说明」+ 新增 `pin=` 探针（见 SaqPinNoteProbe）。
         //   ★★ 第 80 轮（可重复 NPC 入口）：stamp 58 —— 新增 type 101 条目文案
         //     （子项「与他交谈（可重复任务）」+ 可重复任务描述）+ `rep=` 探针
         //     （见 SaqRepeatNpcProbe）。
         //   ★★ 第 81 轮（地球地标任务）：stamp 59 —— **AS3 代码本身没改**，改的是
         //     内嵌回退载荷（加了 10 条「地标任务」+ 其说明文本，SaqEmbeddedPayload.inc）
         //     ⇒ 重编译 SWF 让内嵌数据与 C++ 载荷重新逐条对齐（协议纪律）。
         //   ★★ 第 82 轮（同伴文案说透）：stamp 60 —— 同伴条目的描述首句 + 尾部落点
         //     文案改写（「自动开始 / 不需要找地方接取 / 引导到的是这位同伴的位置」，
         //     见 SaqCompanionNote 与 SaqDescriptionText 的第 4 参数分支）。
         //   ★★ 第 89 轮（可重复任务）：stamp 61 —— 载荷加第 11 列（可重复标记，
         //     见 SaqParsePayload）+ FilterKnownQuests 对「已完成 + 可重复」放行
         //     （做完一次后仍显示）+ `rptk=` 探针（放行名单的运行期证据）。
         //   ★★ 第 91 轮（不可导航提示更明显）：stamp 62 —— 不可导航条目
         //     （bSaqHasTarget = false）的名字加「（不可导航）」前缀
         //     （SaqNotNavigablePrefix / SaqBuildEntry）+ 提示与探针改用原名
         //     （SaqBaseName / sSaqBaseName）+ 新增 `nonav=` 探针（显示名证据）。
         //   ★★ 第 96 轮（可重复任务分组）：stamp 63 —— 可重复任务（bSaqRepeatable）
         //     的显示名加「（可重复）」前缀（SaqRepeatablePrefix / SaqBuildEntry）+
         //     新增 `rq=` 探针（显示名证据）+ `order=` 增加 `|tail=` 段（整组排在
         //     列表末尾的运行期证据，见 MissionsList.SAQ_OrderProbe）。
         _loc8_ += " stamp=63";
         // ★★ 第 51 轮：入口自检（ep=）—— 见 SaqEntryProbe 的说明。
         //   位置在 stamp 之后、其余字段之前：报告有长度上限，这个字段是当前排查
         //   「测试入口调不到」问题的关键证据，必须优先保下来。
         _loc8_ += " ep=" + this.SaqEntryProbe();
         _loc8_ += " last=" + this.SaqTabProbe + " ourTab=" + this.SaqOurTabProbe + " ourTabMax=" + this.SaqOurTabMaxList;
         _loc8_ += " guide=" + this.SaqGuideSeq + "|" + this.SaqGuideQuest + "|" + this.SaqGuideNote;
         // ★ 第 37 轮：本次请求要不要打开星图（R = 1 / Enter = 0）—— 与 `SAQ_PeekGuide`
         //   的第三段同一个值，日志里一眼能看出「这次是设定航线还是只开始引导」。
         _loc8_ += " map=" + (this.SaqGuideWantMap ? "1" : "0");
         // ★ 第 36 轮：代理任务 FormID（0x… = 已知，`0` = 载荷没带 P 行 ⇒ 星图流程降级）
         _loc8_ += " proxy=0x" + Number(this.SaqProxyQuestID).toString(16);
         // ★ 第 42 轮：「玩家按键用的是哪一行」与「列表当前选中项」。
         //   press=[R@0x351a@平衡账目] = 按 R 那一刻界面选的条目；sel=[idx=137:0x351a@…] = 列表选中项。
         //   C++ 侧会把 press/sel 抄进 `引导请求：…` 那一行（见 SAQ.cpp::As3PressNote），
         //   于是「悬停的那条 / 界面用的那条 / C++ 解析出的那条」三者在日志里能一次对齐。
         _loc8_ += " press=[" + this.SaqLastPressNote + "] sel=[" + this.SaqLastSelNote + "]"
            + " btn=[" + this.SaqLastBtnNote + "] ev=[" + this.SaqEventLog.join(" ") + "]";
         // ★★ 第 74 轮（同伴任务分组）：显示列表前 6 条的 uID —— 「同伴任务前置 +
         //   按同伴分组」的**运行期顺序证据**（见 MissionsList.SAQ_OrderProbe）。
         //   ★★ 第 75 轮：四大势力开头任务排在最前（前四条应是 0x2c5401 / 0x29a8f0 /
         //   0x2c9c97 / 0x9136）—— 同一个探针即可判定「固定排前四」。
         if(this.MissionsList_mc != null)
         {
            _loc8_ += " order=[" + this.MissionsList_mc.SAQ_OrderProbe() + "]";
         }
         // ★★ 第 75 轮（四大势力开头任务）：说明真的进了描述（见 SaqPinNoteProbe）。
         _loc8_ += " pin=[" + this.SaqPinNoteProbe() + "]";
         // ★★ 第 80 轮（可重复 NPC 入口）：可重复 NPC 条目计数 + 前 2 条 uID
         //   （见 SaqRepeatNpcProbe；短格式，几乎不占报告长度）。
         _loc8_ += " rep=[" + this.SaqRepeatNpcProbe() + "]";
         // ★★ 第 89 轮（可重复任务）：「已完成 + 可重复 ⇒ 在显示层被放行保留」的
         //   条目计数 + uID 名单（最多 6 条，见 FilterKnownQuests 的 SaqRepeatKept*）。
         //   用例判据：把一条可重复任务推到完成 stage ⇒ 重开菜单 ⇒ 这里应出现它的 uID
         //   （证明「做完一次后仍显示」在**显示层**真的生效，而不只是 C++ 载荷层）。
         _loc8_ += " rptk=[" + this.SaqRepeatKeptCount + "|" + this.SaqRepeatKeptList + "]";
         // ★★ 第 91 轮（不可导航提示更明显）：不可导航条目的计数 + 前 2 条的**显示名**
         //   （`nonav=[<N>|0x<uID>=<显示名>]`）—— 前缀真的进了列表渲染字段（sName）
         //   的运行期证据（见 SaqNotNavigableProbe）。
         _loc8_ += " nonav=[" + this.SaqNotNavigableProbe() + "]";
         // ★★ 第 96 轮（可重复任务分组）：可重复任务的计数 + 前 2 条的**显示名**
         //   （`rq=[<N>|0x<uID>=<显示名>]`）——「（可重复）」前缀真的进了列表渲染
         //   字段（sName）的运行期证据（见 SaqRepeatableQuestProbe）；整组排末尾的
         //   证据见上面的 `order=…|tail=`。
         _loc8_ += " rq=[" + this.SaqRepeatableQuestProbe() + "]";
         // 玩家任务日志名单（第 11 轮，诊断用）：QuestData 的「FormID:名字」，最多 12 条。
         // 用途：玩家说「某条可接任务没找到」时，先看它是不是**已经在玩家日志里**
         // （那样它被 C++/AS3 两层过滤中的某一层正当挡掉）—— 在这个名单里一查便知。
         // 例：qdata[9]=[2ad3d5:全数到期,...] ⇒ 玩家其实已经接过这条任务。
         var _loc9_:String = "";
         if(this.QuestData != null)
         {
            var _loc10_:int = 0;
            while(_loc10_ < this.QuestData.length && _loc10_ < 12)
            {
               if(_loc10_ > 0)
               {
                  _loc9_ += ",";
               }
               _loc9_ += this.QuestData[_loc10_].uID.toString(16) + ":" + this.QuestData[_loc10_].sName;
               _loc10_++;
            }
         }
         _loc8_ += " qdata[" + _loc3_ + "]=[" + _loc9_ + "]";
         // ★ 第 19 轮：被过滤名单（raw 与 keep 的差是哪几条）。放在 qdata **之后**，
         //   但 qdata 最多 12 条 —— 若报告被长度上限截断，先保 qdata（玩家可对照的名字），
         //   drop 只是纯 uID 十六进制（通常 0~5 条），实际几乎不会被截到。
         _loc8_ += " drop[" + this.SaqDropCount + "]=[" + this.SaqDropList + "]";
         // ★★ 第 65 轮（任务专属图标）：图标帧自检 —— 已渲染行的 factionIcon 帧名
         //   （`0x<uID>:<帧名>` 最多 6 条，见 MissionsList.SAQ_IconProbe 的说明）。
         //   数据列对了 ≠ 帧真的切过去了（索引错位 / 帧名拼错 / sprite 结构变化都会
         //   停在第 1 帧）—— 实机日志里的 `icon=[0x…:Constellation,…]` 是图标真的
         //   按原版规则画出来的证据。
         if(this.MissionsList_mc != null)
         {
            _loc8_ += " icon=[" + this.MissionsList_mc.SAQ_IconProbe() + "]";
         }
         return _loc8_;
      }
      
      // ★★ 第 51 轮：入口自检（SAQ_Report 的 ep= 字段）。
      //
      // 起因：06:34 会话里 SWF 已带 stamp=50（证明游戏加载的就是新构建），
      // 但 harness 的 `ui.tab` 仍 0 ms 失败（`_root.SAQ_TestDriveTab=fail`）。
      // 静态排查已排除：入口挂载字节码在（FFDec P-code）、0 参调用正确、
      // 两个 SWF（标准/lrg）都有 —— 所以必须把「运行期到底挂没挂上」报出来。
      //
      //   pub=not-run  → SaqPublishEntryPoint 还没执行（onAddedToStage 没跑）
      //   pub=no-root  → 执行了但 this.root 取不到（挂载被跳过）
      //   pub=ex:…     → 执行时抛异常（异常消息）
      //   pub=ok       → 挂载代码正常跑完
      //   ep=ok             → root 上 11 个入口全在（问题在 Invoke/调用层）
      //   ep=缺:名字,…      → 列出 root 上取不到（不是函数）的入口
      //   ep=no-root / ex:… → 自检本身遇到的环境问题
      //
      // 只读；整段 try-catch 保证绝不把 SAQ_Report 拖崩（它在 500 ms 轮询里被读）。
      private function SaqEntryProbe() : String
      {
         var _loc1_:String = "pub=" + this.SaqPublishNote + ",ep=";
         try
         {
            var _loc2_:Object = this.root;
            if(_loc2_ == null)
            {
               return _loc1_ + "no-root";
            }
            var _loc3_:Array = ["SAQ_SetAvailableQuests","SAQ_Probe","SAQ_Report","SAQ_PeekGuide","SAQ_GuideReply","SAQ_SyncGuideState","SAQ_TestDriveTab","SAQ_TestDriveSelect","SAQ_TestDriveSelectChild","SAQ_TestDriveExpand","SAQ_TestDriveKey","SAQ_TestDriveState"];
            var _loc4_:String = "";
            var _loc5_:int = 0;
            while(_loc5_ < _loc3_.length)
            {
               if(typeof _loc2_[_loc3_[_loc5_]] != "function")
               {
                  _loc4_ += (_loc4_.length > 0 ? "," : "") + _loc3_[_loc5_];
               }
               _loc5_++;
            }
            if(_loc4_.length == 0)
            {
               return _loc1_ + "ok";
            }
            return _loc1_ + "缺:" + _loc4_;
         }
         catch(_loc6_:Error)
         {
            return _loc1_ + "ex:" + _loc6_.message;
         }
      }
      
      // ==================================================================
      //  引导（第 10 轮）
      //
      //  未接取的任务引擎不给标记（它只在「正在运行 + 有已显示目标」时才画），所以引导
      //  走我们自己的代理任务：C++ 侧轮询 SAQ_PeekGuide()，把目标引用写进 ESM 的 GLOB，
      //  Papyrus 那边套到代理任务的别名上。AS3 这一层只负责「玩家想让哪条任务被引导」。
      // ==================================================================
      private function SaqIsOurEntry(param1:Object) : Boolean
      {
         return param1 != null && param1.bSaqAvailable == true;
      }
      
      // ★ 第 42 轮：条目 → 日志标签 `0x<uID 十六进制>@<名字>`（见 SaqLastPressNote 的说明）。
      //   分隔行（bIsDivider 对象）/ 空选中也都安全：给出 "0xNaN@?" 或 "无"，绝不抛异常。
      private function SaqEntryTag(param1:Object) : String
      {
         if(param1 == null)
         {
            return "无";
         }
         var _loc1_:String = param1.sName != null ? String(param1.sName) : "?";
         var _loc3_:Number = Number(param1.uID);
         if(isNaN(_loc3_))
         {
            // ★ 第 48 轮：子项（「前往接取地点」等）没有 uID ⇒ 旧写法会打出「0xNaN」。
            return "「" + _loc1_ + "」(子项)";
         }
         return "0x" + _loc3_.toString(16) + "@" + _loc1_;
      }
      
      // ★ 第 43 轮：把收到的 user event 记进 SaqEventLog（相邻重复不重复记，最多 6 条）。
      //   param2 的语义与原版一致：true = 按下、false = 松开
      //   （原版在 `param1 == "ReturnToStarMap" && param2 == false` 时执行「取消」）。
      //   绝不抛异常（诊断代码不能反过来把菜单带崩）。
      private function SaqNoteUserEvent(param1:String, param2:Boolean) : void
      {
         var _loc1_:String = param1 + (param2 ? "↓" : "↑");
         var _loc2_:int = this.SaqEventLog.length;
         if(_loc2_ > 0 && this.SaqEventLog[_loc2_ - 1] == _loc1_)
         {
            return;
         }
         this.SaqEventLog.push(_loc1_);
         while(this.SaqEventLog.length > 6)
         {
            this.SaqEventLog.shift();
         }
      }
      
      // 条目的显示名：选中的如果是**子项**（「前往接取地点」），名字取它的父任务名 ——
      // 日志/提示里说「已设为引导:<任务名>」才有意义（子项的名字对玩家没有信息量）。
      // ★★ 第 91 轮：统一改走 SaqBaseName —— 提示语里要的是**原名**
      //   （「该任务暂无导航目标:深藏不露」，不是「…:（不可导航）深藏不露」）。
      private function SaqQuestName(param1:Object) : String
      {
         if(param1 == null)
         {
            return "?";
         }
         if(MissionsListEntry.IsMission(param1))
         {
            return this.SaqBaseName(param1);
         }
         var _loc2_:Object = this.FindQuestEntryByID(this.AvailableQuests, param1.uID);
         return _loc2_ != null ? this.SaqBaseName(_loc2_) : param1.sName;
      }
      
      // ★★ 第 91 轮：条目名去掉「（不可导航）」前缀后的**原名**（提示 / 日志用）。
      //   我们建的条目带 sSaqBaseName（SaqBuildEntry 填的）⇒ 用它；
      //   引擎推来的条目 / 子项没这个字段 ⇒ 原样返回 sName（老行为）。
      private function SaqBaseName(param1:Object) : String
      {
         if(param1 == null)
         {
            return "?";
         }
         if(param1.sSaqBaseName != null && String(param1.sSaqBaseName).length > 0)
         {
            return String(param1.sSaqBaseName);
         }
         return param1.sName != null ? String(param1.sName) : "?";
      }
      
      // ★ 第 17 轮：被引导的任务一旦进了玩家任务日志（= 玩家已经接到它了），引导自己消失。
      //
      //   为什么需要：引导是「借」代理任务（SAQ_MainQuest）画出来的 —— 玩家真的接到任务后，
      //   代理任务还挂着「追踪中」，于是 ① HUD 上继续指着那个地点（已经没用了）；
      //   ② 玩家任务日志里一直躺着一条名叫「可接任务」的代理任务。
      //   判据只用**玩家任务日志**（QuestData 里有这个 uID）——这是「已接取」的权威数据
      //   （第 11 轮的结论：TESQuest 的 started 位不算数，见 docs/99 第十一节）。
      //   动作 = 序号 +1、目标清 0（和玩家自己按「取消」走同一条路，DLL 侧无需新协议）。
      private function SaqAutoCancelIfAccepted() : void
      {
         if(this.SaqGuideQuest == 0 || this.QuestData == null)
         {
            return;
         }
         var _loc1_:int = 0;
         while(_loc1_ < this.QuestData.length)
         {
            var _loc2_:Object = this.QuestData[_loc1_];
            if(_loc2_ != null && Number(_loc2_.uID) == this.SaqGuideQuest)
            {
               var _loc3_:Number = this.SaqGuideQuest;
               this.SaqGuideSeq = this.SaqGuideSeq + 1;
               this.SaqGuideQuest = 0;
               this.SaqGuideWantMap = false;   // 第 37 轮：取消方向永远不带星图请求
               this.SaqPendingCloseToGame = false;   // 第 38 轮：同理，不关菜单
               this.SaqGuideNote = "已接取，自动取消引导";
               this.SaqApplyTrackedMarker(_loc3_, 0);
               return;
            }
            _loc1_++;
         }
      }
      
      // 切换引导（返回 true 表示现在是「已设为引导」）。
      //
      // ★ 第 37 轮：param2 = 这一次请求是否要**打开星图**（只有「设定航线（R）」传 true；
      //   点「前往接取地点」子项 / 自动取消都传 false）。取消引导时永远是 false。
      //
      // ★ 第 39 轮：param3 = 是否保留「同一条再按一次 = 取消引导」的切换语义（默认 true）。
      //   只有 Enter（点子项「前往接取地点」）走切换；**SET COURSE（键盘 R / 手柄 X）
      //   传 false** —— 原版按 R 只会「在星图里显示目标位置」（未追踪时再多问一句
      //   是否追踪），**不会**取消已经追踪的任务。此前 R 走切换，于是已引导的条目
      //   再按 R 变成「取消选中」而星图打不开（玩家实测反馈：R 键不该有选中/取消选中的效果）。
      private function SaqToggleGuide(param1:Object, param2:Boolean = false, param3:Boolean = true) : Boolean
      {
         if(!SaqIsOurEntry(param1))
         {
            return false;
         }
         // ★ 第 23 轮：没有导航目标的条目**不发请求** —— 否则界面会「亮起 → 收到结果码 1
         //   → 瞬间回滚」，玩家看到的是「选中后被秒取消」（实测反馈：以为坏了）。
         //   这里直接不动状态、给一声 OFF 音；原因已经写在右侧描述里。
         if(param1.bSaqHasTarget != true)
         {
            this.SaqGuideWantMap = false;   // 第 37 轮：没发请求 ⇒ 也不会有星图
            this.SaqPendingCloseToGame = false;   // 第 38 轮：没发请求 ⇒ 也不关菜单
            GlobalFunc.PlayMenuSound(MISSION_TRACKING_TOGGLE_OFF_SOUND);
            // ★ 第 28 轮：入口条目（任务板）与任务的「不可导航」原因不同 —— 提示分开写。
            // ★ 第 29 轮：常驻化 override 之后这是兜底分支（引用理论上总取得到），
            //   提示语不再说「太远」。
            // ★★ 第 80 轮：入口判据统一用 SaqIsEntryType（任务板 100 / 可重复 NPC 101）。
            if(SaqIsEntryType(param1.iType))
            {
               this.SaqGuideNote = "暂时无法导航:" + this.SaqQuestName(param1);
            }
            else
            {
               this.SaqGuideNote = "该任务暂无导航目标:" + this.SaqQuestName(param1);
            }
            return false;
         }
         // ★ 第 39 轮：已经在这条上（= 重复按 R / 重复点子项）。
         var _loc4_:Boolean = this.SaqGuideQuest == param1.uID;
         // 取消只在「允许切换取消（param3）」时发生；否则永远是「设/保持引导这条」
         // （R 的重复请求因此退化为「把这条再交给星图显示一次」，引导状态原样保留）。
         var _loc2_:Number = _loc4_ && param3 ? 0 : param1.uID;
         var _loc3_:Number = this.SaqGuideQuest;
         this.SaqGuideSeq = this.SaqGuideSeq + 1;
         this.SaqGuideQuest = _loc2_;
         // ★ 第 37 轮：只有「新设定」+「来自设定航线（R）」才带星图请求（取消时一律不带）。
         this.SaqGuideWantMap = param2 && _loc2_ != 0;
         // ★ 第 38 轮：与星图请求同生共死 —— 只有「会打开星图」的请求才需要关整个暂停菜单；
         //   请求被 C++ 拒绝时（回写结果码 != 0）会在 SAQ_GuideReply 里清掉。
         this.SaqPendingCloseToGame = this.SaqGuideWantMap;
         if(_loc2_ != 0)
         {
            if(_loc4_)
            {
               // ★ 第 39 轮：刚刚就在引导这条 ⇒ 不播「开始追踪」音（没有状态变化），
               //   本次请求的实质是「再打开一次星图」（note 进日志，能区分两种按法）。
               this.SaqGuideNote = "重复设定航线:" + this.SaqQuestName(param1);
            }
            else
            {
               GlobalFunc.PlayMenuSound(MISSION_TRACKING_TOGGLE_ON_SOUND);
               this.SaqGuideNote = "已设为引导:" + this.SaqQuestName(param1);
            }
         }
         else
         {
            GlobalFunc.PlayMenuSound(MISSION_TRACKING_TOGGLE_OFF_SOUND);
            this.SaqGuideNote = "已取消引导";
         }
         // ★ 第 13 轮：把「引导中」映射到条目的 bActive —— 列表左侧那条竖条
         //   （TrackIndicator）会像原版「追踪中」的任务一样亮起来。玩家反馈：
         //   我们的条目看起来「永远没被选中」，缺少这个视觉反馈。
         this.SaqApplyTrackedMarker(_loc3_, _loc2_);
         return _loc2_ != 0;
      }
      
      // ==================================================================
      //  ★ 第 44 轮：SET COURSE 的「星图」这一半 —— **不再**走原版 dispatch
      //
      //  第 36 轮起这里会 dispatch 原版的 `MissionMenu_PlotToLocation`（带**代理任务**
      //  SAQ_MainQuest 的 FormID），第 37 轮的离线复核判定「这个事件在引擎里没有 sink」。
      //
      //  ★★ 第 44 轮的实机日志推翻了那个结论：**它其实生效**，而且正是玩家反馈
      //  「R 打开的星图位置永远是上一条任务」的病根。证据（18:34~18:35 会话，DLL 与
      //  Papyrus 双日志对齐）：
      //    ① DLL 写完引导通道后 **9 毫秒**（18:35:00.033 → 18:35:00.042）就探测到星图
      //       已在屏幕上；而脚本那条路要先等菜单关闭、再等它自己的延时 —— 不可能这么快
      //       ⇒ 打开星图的就是这次 dispatch（它在按键那一刻同步发生）；
      //    ② Papyrus 三次「星图请求：1.5 秒后打开」之后**一次都没有**出现
      //       「打开星图并设定航线」—— 因为 dispatch 先把星图打开了 ⇒ 星图是暂停菜单
      //       ⇒ 游戏暂停 ⇒ 脚本定时器冻结 ⇒ 我们那条「用正确目标再开一次」的补救
      //       永远跑不到，玩家看到的就是 dispatch 那一次的结果；
      //    ③ dispatch 用的是**代理任务的当前目标位置**，而那一刻脚本还没 ForceRefTo
      //       （引导更新要等菜单关闭）⇒ 星图拿到的是**上一次**绑定的引用。这正好解释
      //       玩家的原话「我点了阿基拉城任务板，再去点火卫二任务板，导向目标才会是
      //       阿基拉城」；也解释了更早的两条反馈：「所有任务都被导航至沃利阿尔法星」
      //       （别名还没绑定 ⇒ 引擎按默认焦点 = 玩家所在星球打开星图）、
      //       「有一次打开了其他任务的位置」（别名 = 上一条引导的目标）。
      //
      //  ⇒ 现在这里只留「音效 + 日志 note」。星图改由 **Papyrus 脚本**在菜单关闭后
      //    （SAQ_Main.psc 的 ProcessStarMapPending → OpenStarMapFor）用**本次**引导目标
      //    的地点打开（Game.ShowGalaxyStarMapMenuAndPlotToLocation），位置必定是玩家
      //    刚选的那条；`星图:交给脚本(菜单关闭后)` 这行 note 是链路证据。
      //
      //  代理任务的运行期 FormID（SaqProxyQuestID，由载荷的 `P\t<FormID>` 行推来）仍保留：
      //  报告里的 `proxy=0x…` 用于诊断。
      // ==================================================================
      private function SaqNoteStarMapHandoff() : void
      {
         GlobalFunc.PlayMenuSound(MISSION_SHOW_ON_MAP_SOUND);
         this.SaqGuideNote += "｜星图:交给脚本(菜单关闭后)";
      }
      
      // 把「当前引导的任务」写进条目的 bActive，并就地刷新受影响的条目。
      //
      // ★ 第 14 轮修正刷新方式：原来按「数据下标」调 UpdateEntry(QuestData.length + i)，
      //   但列表的**显示下标**并不等于数据下标 —— MissionsList.InitializeEntries 会把
      //   「已完成」条目挪到最后、把 misc 条目挪到末尾，展开时子项还会插进来；
      //   而且 BSScrollingList 根本没有 UpdateEntry 这个接口（那次调用实际被 try 吞掉了）。
      //   现在改成把「要刷新的任务 uID」交给 MissionsList.SAQ_RefreshQuestRow()：
      //   它在**当前显示列表**里按 uID 找行（含已展开的子项），只重渲染找到的那几行，
      //   不动滚动位置、不动展开状态。
      private function SaqApplyTrackedMarker(param1:Number, param2:Number) : void
      {
         if(this.AvailableQuests == null || this.MissionsList_mc == null)
         {
            return;
         }
         var _loc3_:int = 0;
         while(_loc3_ < this.AvailableQuests.length)
         {
            var _loc4_:Object = this.AvailableQuests[_loc3_];
            if(_loc4_ != null && (_loc4_.uID == param1 || _loc4_.uID == param2))
            {
               _loc4_.bActive = param2 != 0 && _loc4_.uID == param2;
               this.MissionsList_mc.SAQ_RefreshQuestRow(_loc4_.uID);
            }
            _loc3_++;
         }
      }
      
      // C++ 侧入口（无参）："<序号>|<任务FormID>|<是否要星图>"。序号 0 = 还没有请求；
      // 序号变化才算一次新请求（C++ 侧据此去重）。
      // ★ 第 37 轮：第三段是新增的（1 = 玩家按的是「设定航线（R）」，0 = Enter / 其它）——
      //   C++ 侧据此决定「要不要关掉任务菜单让脚本打开星图」。旧 SWF 只给两段时
      //   C++ 侧按 0 处理（= 只要蓝点，不打开星图），行为与第 36 轮之前完全一致。
      // ★ 第 38 轮：第四段 = 界面侧会不会自己关掉整个暂停菜单（1/0，见 SaqPendingCloseToGame）。
      //   C++ 侧拿到 1 就不发 kHide（只隐藏任务菜单会停在暂停菜单顶层，游戏不恢复、
      //   脚本定时器不走）。旧 SWF 没有第四段 ⇒ C++ 按 0 处理 ⇒ 旧行为完全不变。
      public function SAQ_PeekGuide() : String
      {
         return this.SaqGuideSeq + "|" + this.SaqGuideQuest + "|" + (this.SaqGuideWantMap ? 1 : 0)
            + "|" + (this.SaqPendingCloseToGame ? 1 : 0);
      }

      // ==================================================================
      //  ★★ 第 49 轮（引擎内 harness）：测试驱动入口
      //
      //  只有 DLL 会调（SAQ_TestOps::InvokeUiTestDrive → _root.SAQ_TestDrive*）。用途：
      //  让「引擎内自动化测试」代替人做「切到可接任务 tab / 选中某条 / 按 R / 点条目」，
      //  于是判据不必每次人肉复现（进游戏一次就能跑完一批用例）。
      //
      //  ★ 关键约定：这些入口**调用真实的处理函数**，不复制任何逻辑 ——
      //    SAQ_TestDriveKey    → ProcessUserEvent（与玩家按键完全同一条链，含按钮启用判定）
      //                          / Accept 走 MissionsList.onEntryPress（与鼠标点击同一条链）
      //    SAQ_TestDriveSelect → 设 selectedIndex 后派发 ScrollingEvent.SELECTION_CHANGE
      //                          （原版列表自己派发的就是同一个事件、同一个处理函数）
      //    SAQ_TestDriveTab    → SetSelectedCategoryIndex + SaqRefresh（与原版切 tab 同一条路）
      //    否则测的就是测试代码，不是产品代码。
      //
      //  返回串约定："ok|…" = 动作已送出（调用方继续断言）；"err|…" = 前置条件不满足。
      // ==================================================================
      public function SAQ_TestDriveTab() : String
      {
         // ★ 第 51 轮：整段包 try-catch —— 若函数内部抛异常，Scaleform 的 Invoke 会
         //   整体失败（表现与「路径不存在」一样是 0 ms 失败），看不出一丝原因；
         //   捕获后把异常消息当 "err|ex:…" 正常返回，失败详情里就能看到真因。
         try
         {
            var _loc1_:int = this.FilterInfoA != null ? int(this.FilterInfoA.length - 1) : -1;
            if(_loc1_ < 0)
            {
               return "err|no-tabs";
            }
            // ★★ 第 52 轮：这里**不能写 `TabbedFilterSelection_mc.selectedIndex`** ——
            //   BSTabbedSelection 的 selectedIndex 只有 getter（只读），赋值会抛
            //   `Error #1074: Illegal write to read-only property`（09-21 06:45 会话
            //   `ui.tab` FAIL 的真因：第 51 轮的 try-catch 把它变成 `err|ex:Error #1074`，
            //   否则看上去和「路径不存在」一模一样）。
            //   程序化切 tab 的原版入口是 MissionTabbedSelection.SetSelectedCategoryIndex
            //   （public；原版「读档恢复上次分类」用的就是它）⇒ 内部 SetSelectedIndex →
            //   派发 BSTabbedSelectionEvent → MissionMenu.onFilterChanged ——
            //   与玩家按肩键 / 点 tab 完全同一条链（掩码同步 + 切换音 + tab 快照）。
            var _loc2_:int = this.currentFilterIndex;
            this.TabbedFilterSelection_mc.SetSelectedCategoryIndex(_loc1_);
            if(this.TabbedFilterSelection_mc.selectedIndex != _loc1_)
            {
               // SetSelectedIndex 静默拒绝（bDisableInput / 越界）—— 报出来，别装作成功
               return "err|tab-refused|from=" + _loc2_ + "|want=" + _loc1_ + "|now=" + this.TabbedFilterSelection_mc.selectedIndex;
            }
            if(_loc2_ == _loc1_)
            {
               // 本来就在这个 tab：SetSelectedIndex 判定「没变化」直接 return、不派发事件
               // ⇒ 原版处理链没跑，这里补一次（掩码/快照不能不同步）
               this.onFilterChanged(null);
            }
            this.SaqRefresh();
            return "ok|tab=" + this.currentFilterIndex + "|mask=" + this.MissionsList_mc.filterMask + "|n=" + this.MissionsList_mc.entryCount;
         }
         catch(_loc9_:Error)
         {
            return "err|ex:" + _loc9_.message;
         }
      }

      public function SAQ_TestDriveSelect(param1:String) : String
      {
         try
         {
            var _loc2_:Number = Number(param1);
            var _loc3_:int = int(this.MissionsList_mc.SAQ_FindEntryIndexByUID(_loc2_));
            if(_loc3_ < 0)
            {
               return "err|notfound|n=" + this.MissionsList_mc.entryCount;
            }
            this.MissionsList_mc.selectedIndex = _loc3_;
            this.MissionsList_mc.dispatchEvent(new ScrollingEvent(ScrollingEvent.SELECTION_CHANGE));
            return "ok|idx=" + _loc3_ + "|" + this.SaqEntryTag(this.MissionsList_mc.selectedEntry);
         }
         catch(_loc9_:Error)
         {
            return "err|ex:" + _loc9_.message;
         }
      }

      // ★★ 第 54 轮（harness）：选中某条目的**子项**（「前往接取地点」/「前往任务板」）。
      //
      //   为什么需要：Enter 的引导路径与原版对齐 —— 主标题上的 Enter 只做「展开/收起」
      //   （见 onMissionListItemActivated），**只有子项**上的 Enter 才切换引导。而
      //   「只引导、不开星图」（map=0、菜单不关）这条链只有走子项才能验 ——
      //   第 26 轮的历史判据「在菜单里久停 27 秒不出现假失败」需要的正是它
      //   （按 R 的那条链会在成功回写后由界面关掉整个暂停菜单，没法久停）。
      //
      //   内部仍走真实路径：ExpandOrCollapseSelection（原版展开）+ 设 selectedIndex +
      //   派发 ScrollingEvent.SELECTION_CHANGE（原版列表自己派发的就是它）——
      //   接下来的 `ui.key Accept` 会落到 MissionsList.onEntryPress → ITEM_ACTIVATED
      //   → onMissionListItemActivated 的**子项分支**（SaqToggleGuide）。
      public function SAQ_TestDriveSelectChild(param1:String) : String
      {
         try
         {
            var _loc2_:Number = Number(param1);
            var _loc3_:int = int(this.MissionsList_mc.SAQ_FindEntryIndexByUID(_loc2_));
            if(_loc3_ < 0)
            {
               return "err|notfound|n=" + this.MissionsList_mc.entryCount;
            }
            this.MissionsList_mc.selectedIndex = _loc3_;
            var _loc4_:Object = this.MissionsList_mc.selectedEntry;
            if(_loc4_ != null && _loc4_.expanded != true)
            {
               this.MissionsList_mc.ExpandOrCollapseSelection();
            }
            var _loc5_:int = int(this.MissionsList_mc.SAQ_FindChildIndexByUID(_loc2_));
            if(_loc5_ < 0)
            {
               return "err|no-child|n=" + this.MissionsList_mc.entryCount;
            }
            this.MissionsList_mc.selectedIndex = _loc5_;
            this.MissionsList_mc.dispatchEvent(new ScrollingEvent(ScrollingEvent.SELECTION_CHANGE));
            return "ok|idx=" + _loc5_ + "|" + this.SaqEntryTag(this.MissionsList_mc.selectedEntry);
         }
         catch(_loc10_:Error)
         {
            return "err|ex:" + _loc10_.message;
         }
      }

      public function SAQ_TestDriveExpand(param1:String) : String
      {
         try
         {
            var _loc2_:Number = Number(param1);
            var _loc3_:int = int(this.MissionsList_mc.SAQ_FindEntryIndexByUID(_loc2_));
            if(_loc3_ < 0)
            {
               return "err|notfound";
            }
            this.MissionsList_mc.selectedIndex = _loc3_;
            this.MissionsList_mc.ExpandOrCollapseSelection();
            this.MissionsList_mc.dispatchEvent(new ScrollingEvent(ScrollingEvent.SELECTION_CHANGE));
            return "ok|idx=" + _loc3_ + "|n=" + this.MissionsList_mc.entryCount;
         }
         catch(_loc9_:Error)
         {
            return "err|ex:" + _loc9_.message;
         }
      }

      public function SAQ_TestDriveKey(param1:String) : String
      {
         try
         {
            if(param1 == "Accept" || param1 == "Enter" || param1 == "Click")
            {
               // 回车 / 鼠标点击：原版由输入层**直接送给列表**（不是菜单的 ProcessUserEvent）
               // ⇒ 这里走 MissionsList.onEntryPress（它内部 stopPropagation + onItemPress，
               //   并派发 ITEM_ACTIVATED）—— 与真实点击完全同一条链。
               this.MissionsList_mc.onEntryPress(new Event(Event.CLICK));
               return "ok|entryPress|" + this.SaqLastPressNote;
            }
            // 其余（XButton = 键盘 R / 手柄 X、YButton、Cancel…）：与玩家按键完全相同的那条链
            // （ProcessUserEvent → SaqNoteUserEvent → ButtonBar → 按钮回调，含按钮启用判定）。
            var _loc2_:Boolean = this.ProcessUserEvent(param1,false);
            return "ok|menu=" + (_loc2_ ? 1 : 0) + "|" + this.SaqLastPressNote;
         }
         catch(_loc9_:Error)
         {
            return "err|ex:" + _loc9_.message;
         }
      }

      // 给断言用的短状态（比 SAQ_Report 轻，跑用例时每一步都能打一行）。
      public function SAQ_TestDriveState() : String
      {
         try
         {
            return "tab=" + this.currentFilterIndex + "|mask=" + this.MissionsList_mc.filterMask
               + "|n=" + this.MissionsList_mc.entryCount + "|sel=" + this.MissionsList_mc.selectedIndex
               + "|avail=" + (this.AvailableQuests != null ? this.AvailableQuests.length : -1);
         }
         catch(_loc9_:Error)
         {
            return "err|ex:" + _loc9_.message;
         }
      }

      // ★ 第 38 轮：C++ 回写成功后的「关菜单」这一步（见 SaqPendingCloseToGame 的说明）。
      //   `CloseMenu(true)` = 原版「退回游戏」路径：
      //     设置 bReturningToGame → StartGameRender + DataMenu_SetMenuForQuickEntry
      //     → 播关闭动画 → OnTimelineCloseEvent → SaveMissionMenuState + GlobalFunc.CloseAllMenus()
      //   整个暂停菜单随之关掉 —— 游戏恢复运行，脚本的轮询节拍随即推进
      //   （★ 第 44 轮起：约 0.5~1 秒后由 Papyrus 的 ProcessStarMapPending 打开星图，
      //    用的是本次引导目标的地点；见 SaqNoteStarMapHandoff 的说明）。
      private function SaqReturnToGameForStarMap() : void
      {
         if(!this.SaqPendingCloseToGame)
         {
            return;
         }
         this.SaqPendingCloseToGame = false;
         this.SaqGuideNote += "｜星图:菜单已交界面关闭";
         try
         {
            this.CloseMenu(true);
         }
         catch(_loc1_:Error)
         {
            this.SaqGuideNote += "关菜单异常:" + _loc1_.message;
         }
      }
      
      // 按 uID 找一条可接任务的显示名（引导相关文案用；找不到给 "?"）。
      // 显示名：优先在「可接列表」里找（AvailableQuests），找不到再查**玩家任务日志**
      // （QuestData —— 任务被接取后就会从可接列表消失，但日志里还在）。
      // ★ 第 48 轮：旧写法只查可接列表 ⇒ 玩家刚接取任务时状态栏会显示「当前引导:?」。
      //   最后兜底打 FormID（绝不再出现「?」）。
      private function SaqQuestNameByID(param1:Number) : String
      {
         var _loc2_:Object = this.FindQuestEntryByID(this.AvailableQuests, param1);
         if(_loc2_ != null)
         {
            return _loc2_.sName;
         }
         var _loc3_:Object = this.FindQuestEntryByID(this.QuestData, param1);
         if(_loc3_ != null)
         {
            return _loc3_.sName;
         }
         return "0x" + Number(param1).toString(16);
      }
      
      // ==================================================================
      //  C++ → 界面 · 回写通道（第 16 轮）
      //
      //  为什么需要它：SaqToggleGuide 只能在本地「立刻」切状态（音效 / 竖条 / 文案），
      //  但「这条任务到底有没有引导目标」只有 C++ 侧知道（静态表里的 guideRef）。
      //  没有回写时，玩家点到**没有引导目标**的任务（202 条里 34 条）会看到
      //  「已设为引导」，实际什么都没发生 —— 而且旧引导如果还在，游戏里指的仍是旧任务。
      //
      //  协议："<seq>|<实际引导任务FormID>|<结果码>"
      //    结果码：0=成功 / 1=该任务没有引导目标 / 2=写 ESM 通道失败 / 3=静态表里没有这条
      //           ★ 第 19 轮新增 4 = 引导未生效（脚本确认超时 / 别名不存在）——
      //           C++ 侧做过确认（PollGuideVerify）后仍未生效，必须回滚界面，
      //           否则界面会一直显示「已设为引导」而世界里什么都没有（界面说谎）。
      //           ★★ 第 46 轮新增 5 = 「已排定，但目标的引用此刻还没加载」（玩家在远处
      //           点了候选全是非常驻的任务）—— **不回滚**：引导保持、竖条不灭、不播
      //           OFF 音、不关菜单（星图这次也不开）；C++ 侧会保持待生效并自动重试，
      //           玩家靠近目标区域后蓝点自动出现（脚本侧另有 HUD 提示）。
      //  语义：**以「实际值」为准**——界面把 SaqGuideQuest 对齐到 C++ 报的实际值，
      //  与本地状态不一致时就是「被拒绝」，回滚竖条并给出失败文案。
      // ==================================================================
      public function SAQ_GuideReply(param1:String) : String
      {
         if(param1 == null)
         {
            return "bad";
         }
         var _loc2_:Array = param1.split("|");
         if(_loc2_.length < 3)
         {
            return "bad";
         }
         var _loc3_:int = int(_loc2_[0]);
         if(_loc3_ != this.SaqGuideSeq)
         {
            // 玩家已经又点了别的（或界面换代）—— 过期应答，忽略。
            return "stale";
         }
         var _loc4_:Number = Number(_loc2_[1]);
         var _loc5_:int = int(_loc2_[2]);
         var _loc6_:Number = this.SaqGuideQuest;
         if(_loc4_ == _loc6_ && _loc5_ == 0)
         {
            // 成功且状态一致：本地早已切好（音效/文案/竖条都不动）
            // ★ 第 38 轮：这是「设定航线（R）」的常见分支 —— 此刻 C++ 已把状态 5 写好，
            //   可以让界面侧关掉整个暂停菜单了（见 SaqReturnToGameForStarMap）。
            this.SaqReturnToGameForStarMap();
            return "same";
         }
         this.SaqGuideQuest = _loc4_;
         if(_loc5_ == 0)
         {
            this.SaqGuideNote = _loc4_ != 0 ? "已设为引导:" + this.SaqQuestNameByID(_loc4_) : "已取消引导";
            // ★ 第 38 轮：成功 ⇒ 若这次请求带星图意图，现在关菜单。
            this.SaqReturnToGameForStarMap();
         }
         else if(_loc5_ == 5)
         {
            // ★★ 第 46 轮：目标尚未加载 —— 引导**保持**（竖条不灭）：C++ 侧会保持待生效
            //   并自动重试，玩家靠近后自动生效。所以这里：不回滚、不播 OFF 音、
            //   不关菜单、不开星图（DLL 也没写状态 5、没安排星图）。
            this.SaqGuideWantMap = false;
            this.SaqPendingCloseToGame = false;
            this.SaqGuideNote = "目标尚未加载:靠近后自动生效";
         }
         else
         {
            // 被拒绝：回滚到「实际值」，给失败反馈（OFF 音 = 与原版「取消追踪」同款提示）
            // ★ 第 37 轮：拒绝 ⇒ 星图也不会开（DLL 只在成功路径上关菜单、写状态 5），
            //   把本地的星图标记一并清掉，免得日志/后续请求带错意图。
            this.SaqGuideWantMap = false;
            // ★ 第 38 轮：被拒绝 ⇒ 更不能关菜单（星图不会开，关了只会把玩家踢出菜单）。
            this.SaqPendingCloseToGame = false;
            GlobalFunc.PlayMenuSound(MISSION_TRACKING_TOGGLE_OFF_SOUND);
            if(_loc5_ == 1)
            {
               this.SaqGuideNote = "该任务暂无引导目标";
            }
            else if(_loc5_ == 2)
            {
               this.SaqGuideNote = "引导通道写入失败";
            }
            else if(_loc5_ == 4)
            {
               // ★ 第 19 轮：脚本没响应（确认超时 / 别名不存在）——必须回滚。
               this.SaqGuideNote = "引导未生效:脚本未响应";
            }
            else
            {
               this.SaqGuideNote = "引导失败:任务不在静态表";
            }
         }
         this.SaqApplyTrackedMarker(_loc6_, _loc4_);
         return "ok";
      }
      
      // ==================================================================
      //  C++ → 界面 · 状态同步（第 16 轮）
      //
      //  菜单每次打开都是**新的 SWF 实例**（SaqGuideQuest 归 0），而引导可能还在生效
      //  （蓝点还指着某个地方）。不同步的话有两个毛病：
      //    ① 列表重建时 SaqBuildEntry 的 bActive 读 0 ⇒ 引导中那条的竖条丢了；
      //    ② 对「正在引导的那条」第一次点击会被算成「设置引导」而不是「取消」。
      //  只在玩家还没操作过（SaqGuideSeq == 0）时接受同步 —— 否则会覆盖玩家刚做的操作
      //  （那种情况的结果由 SAQ_GuideReply 回来）。
      // ==================================================================
      public function SAQ_SyncGuideState(param1:String) : String
      {
         if(this.SaqGuideSeq != 0)
         {
            return "skip";
         }
         var _loc2_:Number = Number(param1);
         var _loc3_:Number = this.SaqGuideQuest;
         if(_loc2_ == _loc3_)
         {
            return "same";
         }
         this.SaqGuideQuest = _loc2_;
         this.SaqGuideNote = _loc2_ != 0 ? "当前引导:" + this.SaqQuestNameByID(_loc2_) : "-";
         this.SaqApplyTrackedMarker(_loc3_, _loc2_);
         return "ok";
      }
      
      private function OnQuestDataUpdate(param1:FromClientDataEvent) : void
      {
         this.QuestData = param1.data.aQuests;
         if(this.RawAvailableQuests != null)
         {
            this.AvailableQuests = this.FilterKnownQuests(this.RawAvailableQuests);
         }
         this.CollapseAllChildren();
         this.lastSelectedIndex = -1;
         // 任务名到手了 —— 语言判定与「已接任务」过滤都在这里一并重算
         // （SaqRefresh 内部会 InitializeEntries(BuildMergedList())）
         this.SaqRefresh();
         if(this.visible)
         {
            stage.focus = this.MissionsList_mc;
            if(this.QuestData.length > 0 && this.MissionsList_mc.selectedIndex == -1)
            {
               this.MissionsList_mc.selectedIndex = 0;
            }
            if(this.scrollPositionAtTracking)
            {
               this.MissionsList_mc.scrollPosition = this.scrollPositionAtTracking;
            }
            this.scrollPositionAtTracking = -1;
            this.onMissionSelectionChange();
         }
         else
         {
            this.MissionsList_mc.selectedIndex = -1;
         }
         this.InitializeLastState();
      }
      
      public function onStickDataChanged(param1:FromClientDataEvent) : *
      {
         this.MissionInfo_mc.ProcessStickData(param1);
      }
      
      public function onMissionMenuStateData(param1:FromClientDataEvent) : *
      {
         this.StoredLastOpenedIds = param1.data.aOpenQuestIds;
         this.StoredLastCategory = param1.data.uCategoryIndex;
         this.SetQTDisplayFlag(param1.data.bShowOnlyActiveQTs);
         this.InitializeLastState();
      }
      
      public function onFireForgetEvent(param1:FromClientDataEvent) : *
      {
         if(GlobalFunc.HasFireForgetEvent(param1.data,"MissionMenu_TransitionToMap"))
         {
            this.CloseMenu(false);
         }
      }
      
      override public function onAddedToStage() : void
      {
         super.onAddedToStage();
         BSUIDataManager.Subscribe("QuestData",this.OnQuestDataUpdate);
         BSUIDataManager.Subscribe("MissionMenuStickData",this.onStickDataChanged);
         BSUIDataManager.Subscribe("MissionMenuStateData",this.onMissionMenuStateData);
         BSUIDataManager.Subscribe("FireForgetEventData",this.onFireForgetEvent);
         GlobalFunc.PlayMenuSound("UIMenuMissionsMenuEnter");
         this.KeyHelper = new ButtonKeyHelper();
         // root 上挂一份 C++ 插件用的入口（见 SaqPublishEntryPoint 注释）
         this.SaqPublishEntryPoint();
      }
      
      override protected function OnPlatformChanged(param1:Object) : void
      {
         super.OnPlatformChanged(param1);
         this.TabbedFilterSelection_mc.Configure(CategoryTab,BSTabbedSelection.CENTER_ALIGNED,BSTabbedSelection.DEFAULT_SPACING,uiController == PlatformUtils.PLATFORM_PC_KB_MOUSE ? ["LShoulder","Left"] : ["LShoulder"],uiController == PlatformUtils.PLATFORM_PC_KB_MOUSE ? ["RShoulder","Right"] : ["RShoulder"]);
      }
      
      private function onFilterChanged(param1:BSTabbedSelectionEvent) : *
      {
         this.bSkipSelectionSounds = true;
         this.CollapseAllChildren();
         this.MissionsList_mc.filterMask = this.currentFilterFlag;
         if(this.MissionsList_mc.entryCount > 0)
         {
            this.MissionsList_mc.selectedIndex = 0;
         }
         GlobalFunc.PlayMenuSound(MISSION_CATEGORY_CHANGE_SOUND);
         this.bSkipSelectionSounds = false;
         this.SaqSnapshotTab("switch");
      }
      
      private function CollapseAllChildren() : *
      {
         this.bCollapsing = true;
         if(this.bWithinMiscQuest)
         {
            this.MissionsList_mc.ShowEntryChildren(this.miscQuestIndex,false);
         }
         else
         {
            this.MissionsList_mc.ShowEntryChildren(this.lastSelectedIndex,false);
         }
         this.lastSelectedIndex = -1;
         this.bCollapsing = false;
      }
      
      public function ProcessUserEvent(param1:String, param2:Boolean) : Boolean
      {
         this.SaqNoteUserEvent(param1,param2);   // ★ 第 43 轮：诊断探针（见 SaqEventLog）
         var _loc3_:Boolean = false;
         if(param1 == "ReturnToStarMap" && param2 == false)
         {
            this.OnCancelEvent();
            _loc3_ = true;
         }
         else if(param1 == "Missions" && param2 == false)
         {
            this.onCloseSubMenuToGame();
            _loc3_ = true;
         }
         _loc3_ = this.ButtonBar_mc.ProcessUserEvent(param1,param2);
         if(!_loc3_)
         {
            _loc3_ = this.TabbedFilterSelection_mc.ProcessUserEvent(param1,param2);
         }
         return _loc3_;
      }
      
      private function SetQTDisplayFlag(param1:Boolean) : void
      {
         if(this.ShowOnlyActiveQTs != param1)
         {
            this.ShowOnlyActiveQTs = param1;
            this.ToggleQTDisplayButton.SetButtonData(this.ShowOnlyActiveQTs ? this.ShowAllQTsBtnData : this.ShowOnlyActiveQTsBtnData);
         }
      }
      
      private function ToggleQTDisplay() : void
      {
         BSUIDataManager.dispatchEvent(new Event("MissionMenu_ToggleQTDisplay"));
      }
      
      // 按 uID 在一份条目数组里找主条目（找不到给 null）。
      private function FindQuestEntryByID(param1:Array, param2:Number) : Object
      {
         if(param1 == null)
         {
            return null;
         }
         var _loc3_:int = 0;
         while(_loc3_ < param1.length)
         {
            if(param1[_loc3_] != null && param1[_loc3_].uID == param2)
            {
               return param1[_loc3_];
            }
            _loc3_++;
         }
         return null;
      }
      
      private function GetParentMissionData(param1:Object) : Object
      {
         if(param1 == null)
         {
            return null;
         }
         if(MissionsListEntry.IsMission(param1))
         {
            return param1;
         }
         if(param1.bIsMiscObjective != null && param1.bIsMiscObjective !== false)
         {
            return null;
         }
         var _loc2_:Object = this.FindQuestEntryByID(this.QuestData,param1.uOwnerQuestFormID);
         // ★ 第 14 轮：我们的可接任务在引擎/玩家日志里都不存在（还没接取），
         //   只在本菜单的 AvailableQuests 里 —— 子项要能找到父任务，右侧详情面板
         //   才会像原版那样显示这条任务的内容。
         if(_loc2_ == null)
         {
            _loc2_ = this.FindQuestEntryByID(this.AvailableQuests,param1.uOwnerQuestFormID);
         }
         return _loc2_;
      }
      
      public function onMissionSelectionChange() : *
      {
         var _loc1_:Object = this.MissionsList_mc.selectedEntry;
         // ★ 第 42 轮：记下「列表当前选中的那一行」（鼠标悬停、键盘上下、程序设置都会走到这里）
         //   —— 进报告的 sel=[…]，与 press=[…]（玩家按键那一刻用的行）对照，
         //   两者不是同一条 ⇒ 「按键用的是哪一行」与「鼠标悬停的是哪一行」不一致（可查的 bug）。
         this.SaqLastSelNote = "idx=" + this.MissionsList_mc.selectedIndex + ":" + this.SaqEntryTag(_loc1_);
         var _loc2_:Boolean = _loc1_ != null ? MissionsListEntry.IsMission(_loc1_) : false;
         var _loc3_:Object = null;
         if(!_loc2_)
         {
            _loc3_ = this.GetParentMissionData(_loc1_);
         }
         if(_loc1_ != null)
         {
            this.CanTrackOrUntrack = !_loc2_;
            if(this.CanTrackOrUntrack)
            {
               if(_loc3_ == null || _loc3_.uID == 0)
               {
                  this.CanTrackOrUntrack = Boolean(_loc1_.bIsMiscObjective) && !_loc1_.bComplete;
               }
               else
               {
                  this.CanTrackOrUntrack = !_loc3_.bComplete;
               }
            }
            this.UpdateRejectData(_loc1_.bCanBeRejected === true && (_loc3_ == null || _loc3_.uID == 0));
            this.ShowOnMapButton.Enabled = MissionsListEntry.CanShowOnMap(_loc1_) != 0;
            this.PlotToLocationButton.Enabled = MissionsListEntry.CanShowOnMap(_loc1_) != 0;
            if(this.SaqIsOurEntry(_loc1_))
            {
               // 「可接任务」条目：原版没有它的位置数据（Y 显示在地图上不给用），
               // SET COURSE（键盘 R / 手柄 X）改用我们自己的引导 —— 见 OnPlotCourseEvent。
               this.ShowOnMapButton.Enabled = false;
               // ★ 第 23 轮：没有导航目标的条目 → SET COURSE 置灰（点了也没用，别让玩家困惑）。
               // ★ 第 43 轮：**取消置灰** —— 置灰是「沉默失败」：按 R 时既没有提示、也不留
               //   任何日志痕迹（本轮排查「按 R 没反应」时连「按键有没有到界面」都无从判断，
               //   就是它把现场抹掉了）。改回可点：没有导航目标时会走 SaqToggleGuide 的
               //   「该任务暂无导航目标」分支（界面提示 + OFF 音、不发请求）—— 正合需求
               //   「不可引导要提示玩家，而不是单纯无法选中」。
               this.PlotToLocationButton.Enabled = true;
            }
            if(_loc2_ || _loc1_.bIsMiscObjective === true)
            {
               this.MissionInfo_mc.UpdateMissionInfo(this.MissionsList_mc.selectedEntry);
            }
            else if(_loc3_)
            {
               this.MissionInfo_mc.UpdateMissionInfo(_loc3_);
            }
         }
         else
         {
            this.ShowOnMapButton.Enabled = false;
            this.PlotToLocationButton.Enabled = false;
            this.CanTrackOrUntrack = false;
            this.UpdateRejectData(false);
         }
         if(_loc2_)
         {
            this.lastSelectedIndex = this.MissionsList_mc.selectedIndex;
         }
         if(!this.bSkipSelectionSounds)
         {
            GlobalFunc.PlayMenuSound(MISSION_SELECTION_CHANGE_SOUND);
            GlobalFunc.PlayMenuSound(MISSION_SUBTASK_TOGGLE_SOUND);
         }
         this.bSkipSelectionSounds = false;
         // ★ 第 43 轮：把这一刻的按钮状态记进报告 —— 诊断「按 R 没反应」的关键数据：
         //   our/std 区分「我们的条目」是否被识别（bSaqAvailable 是否还在），
         //   plot/map = 两个按钮此刻是启用(1)还是置灰(0)。
         this.SaqLastBtnNote = (this.SaqIsOurEntry(_loc1_) ? "our" : "std")
            + ":plot=" + (this.PlotToLocationButton != null && this.PlotToLocationButton.Enabled ? 1 : 0)
            + ":map=" + (this.ShowOnMapButton != null && this.ShowOnMapButton.Enabled ? 1 : 0);
      }
      
      override protected function OnControlMapChanged(param1:Object) : void
      {
         super.OnControlMapChanged(param1);
         if(this.KeyHelper != null)
         {
            this.KeyHelper.OnControlMapChanged(param1);
         }
         this.PopulateButtonBar();
         if(uiController == PlatformUtils.PLATFORM_PC_KB_MOUSE)
         {
            this.TabbedFilterSelection_mc.LeftButton.y = this.startingTabButtonYPosition + KEYBOARD_TAB_BUTTON_OFFSET;
            this.TabbedFilterSelection_mc.RightButton.y = this.startingTabButtonYPosition + KEYBOARD_TAB_BUTTON_OFFSET;
            this.TabbedFilterSelection_mc.UpdateButtonUserEvents(["Left"],["Right"]);
         }
         else
         {
            this.TabbedFilterSelection_mc.LeftButton.y = this.startingTabButtonYPosition;
            this.TabbedFilterSelection_mc.RightButton.y = this.startingTabButtonYPosition;
            this.TabbedFilterSelection_mc.UpdateButtonUserEvents(["LShoulder","Left"],["RShoulder","Right"]);
         }
      }
      
      private function OnCancelEvent() : void
      {
         this.CloseMenu(false);
      }
      
      private function onCloseSubMenuToGame() : *
      {
         this.CloseMenu(true);
      }
      
      private function CloseMenu(param1:Boolean) : *
      {
         if(!this.bClosing)
         {
            this.bClosing = true;
            this.bReturningToGame = param1;
            if(param1)
            {
               GlobalFunc.StartGameRender();
               BSUIDataManager.dispatchEvent(new Event("DataMenu_SetMenuForQuickEntry"));
            }
            gotoAndPlay("Close");
         }
      }
      
      private function OnTimelineCloseEvent() : void
      {
         this.SaveMissionMenuState();
         GlobalFunc.PlayMenuSound("UIMenuMissionsMenuExit");
         if(this.bReturningToGame)
         {
            GlobalFunc.CloseAllMenus();
         }
         else
         {
            GlobalFunc.CloseMenu("BSMissionMenu");
         }
      }
      
      private function OnShowOnMapEvent() : void
      {
         if(MissionsListEntry.IsMission(this.MissionsList_mc.selectedEntry))
         {
            BSUIDataManager.dispatchEvent(new CustomEvent(SHOW_ITEM_LOCATION_EVENT,{
               "questID":this.MissionsList_mc.selectedEntry.uID,
               "objectiveID":-1
            }));
         }
         else
         {
            BSUIDataManager.dispatchEvent(new CustomEvent(SHOW_ITEM_LOCATION_EVENT,{
               "questID":this.MissionsList_mc.selectedEntry.uOwnerQuestFormID,
               "objectiveID":this.MissionsList_mc.selectedEntry.uIndex
            }));
         }
         GlobalFunc.PlayMenuSound(MISSION_SHOW_ON_MAP_SOUND);
      }
      
      private function OnPlotCourseEvent() : void
      {
         // ★ 第 42 轮（玩家反馈「R 的导航目标有时不是鼠标悬停的那条」）两处加固：
         //   ① **按键这一刻先钉住用的是哪一行**（进报告 press=[…]，C++ 侧抄进引导请求日志）
         //      —— 「界面选了哪条」从此有硬证据，不再只能推断；
         //   ② 选中项为空（悬停到分隔行 / 还没渲染的行）时直接返回：下面的原版分支里
         //      `MissionsListEntry.IsMission(undefined)` 会在 hasOwnProperty 上抛异常，
         //      异常冒到按钮栏会被吞掉 —— 玩家看到的是「按 R 没反应」（也是「不稳定」的一种）。
         var _loc1_:Object = this.MissionsList_mc.selectedEntry;
         this.SaqLastPressNote = "R@" + this.SaqEntryTag(_loc1_);
         if(_loc1_ == null)
         {
            return;
         }
         // 「可接任务」条目：SET COURSE（键盘 R / 手柄 X）改成我们自己的引导请求，
         // 不把不存在的任务 ID 丢给原版的数据层（那样只会静默失败）。
         if(this.SaqIsOurEntry(_loc1_))
         {
            // ★ 第 36 轮：行为与原版对齐 —— SET COURSE 除了「设定引导」，还要走**原版的
            //   星图流程**（打开星图 → 聚焦到接取地点所在星球 → 询问玩家是否导航）。
            //
            //   怎么做到「原版流程」：引擎处理 MissionMenu_PlotToLocation 时只需要一个
            //   **真实存在、且带「已显示目标」的任务** —— 我们的代理任务（SAQ_MainQuest）
            //   正是为此而生的：它的目标别名（SAQ_GuideTarget）此刻已经绑在「接取地点」
            //   引用上（ForceRefTo）。所以把**代理任务**的 FormID 传进去，引擎就会
            //   像对待原版任务一样：算出目标位置 → 打开星图 → 聚焦星球 → 询问导航。
            //
            // ★ 第 37 轮：R = 「设定航线」——把自己引导 + **打开星图**（第二参数）。
            //
            // ★ 第 39 轮：第三参数 false = **R 永远不取消引导**。
            //   原版：未追踪 → 星图打开并询问是否追踪；已追踪 → 星图直接显示目标位置。
            //   我们的对应实现：无论哪种情况，都「保持/建立引导 + 请求星图」——
            //   已引导的条目再按 R，只是把这条任务再交给星图显示一次（序号 +1，C++ 会
            //   再写一遍通道并触发「关菜单 → 脚本开星图」），而不是取消条目
            //   （此前正是「已选中的任务按 R = 取消选中、星图打不开」，玩家实测反馈）。
            //   取消引导仍有一条路：Enter 选中子项「前往接取地点」（默认 param3 = true）。
            // ★ 第 42 轮：改用上面已经取好的 _loc1_（同一行对象），不再重读 selectedEntry ——
            //   避免「按键时读一次、真正引导时又读一次」之间被列表重建换掉（两次读到不同行）。
            // ★★ 第 44 轮：这里**不再** dispatch 原版 MissionMenu_PlotToLocation（那个
            //   dispatch 其实生效，但用的是代理任务**上一次**的目标位置 ⇒ 星图位置滞后
            //   一条，见 SaqNoteStarMapHandoff 的说明）。只留音效 + note；星图由 Papyrus
            //   在菜单关闭后用本次引导目标的地点打开。
            var _loc2_:Boolean = this.SaqToggleGuide(_loc1_, true, false);
            if(_loc2_)
            {
               this.SaqNoteStarMapHandoff();
            }
            return;
         }
         if(MissionsListEntry.IsMission(_loc1_))
         {
            BSUIDataManager.dispatchEvent(new CustomEvent(MissionMenu_PlotToLocation,{
               "questID":_loc1_.uID,
               "objectiveID":-1
            }));
         }
         else
         {
            BSUIDataManager.dispatchEvent(new CustomEvent(MissionMenu_PlotToLocation,{
               "questID":_loc1_.uOwnerQuestFormID,
               "objectiveID":_loc1_.uIndex
            }));
         }
         GlobalFunc.PlayMenuSound(MISSION_SHOW_ON_MAP_SOUND);
      }
      
      private function onMissionListItemActivated() : void
      {
         var _loc1_:* = undefined;
         var _loc2_:Boolean = false;
         var _loc3_:Object = null;
         // 「可接任务」条目的 Enter / 鼠标点击 —— 交互与原版对齐（第 14 轮修正）：
         //   · 主标题（有子项）：**不**切换引导 —— 这一步只做「展开/收起」，由
         //     BSScrollingTree.onEntryPress 自己完成（原版点任务主标题也是展开）；
         //   · 子项（「前往接取地点」）：切换引导 —— 对应原版「点目标切换追踪」，
         //     主标题左侧的竖条（TrackIndicator）随之点亮（引导中 = 追踪中的视觉）。
         // 必须在 CanTrackOrUntrack 判定**之前**处理：我们的条目在引擎侧不存在，
         // 落进原版分支会往数据层发一条引擎找不到的任务 ID。
         // ★ 第 42 轮：Enter 也记一行 press=[E@…]（与 R 的 press=[R@…] 区分）——
         //   「只引导」与「设定航线」两条路各自的入口条目都能在日志里对上。
         if(this.SaqIsOurEntry(this.MissionsList_mc.selectedEntry))
         {
            this.SaqLastPressNote = "E@" + this.SaqEntryTag(this.MissionsList_mc.selectedEntry);
            if(!MissionsListEntry.IsMission(this.MissionsList_mc.selectedEntry))
            {
               this.SaqToggleGuide(this.MissionsList_mc.selectedEntry);
            }
            return;
         }
         var _loc4_:String = this.SaqEntryTag(this.MissionsList_mc.selectedEntry);
         if(_loc4_ != "无")
         {
            this.SaqLastPressNote = "E(原版)@" + _loc4_;
         }
         if(this.CanTrackOrUntrack)
         {
            _loc1_ = this.MissionsList_mc.selectedEntry;
            if(_loc1_ != null)
            {
               this.bSkipSelectionSounds = true;
               this.MissionsList_mc.StoreCurrentListState();
               if(_loc1_.bIsMiscObjective === true)
               {
                  if(_loc1_.bActive)
                  {
                     GlobalFunc.PlayMenuSound(MISSION_TRACKING_TOGGLE_OFF_SOUND);
                  }
                  else
                  {
                     GlobalFunc.PlayMenuSound(MISSION_TRACKING_TOGGLE_ON_SOUND);
                  }
                  this.scrollPositionAtTracking = this.MissionsList_mc.scrollPosition;
                  this.MissionsList_mc.selectedIndex = -1;
                  BSUIDataManager.dispatchEvent(new CustomEvent(MissionMenu_ToggleTrackingQuest,{
                     "questID":_loc1_.uOwnerQuestFormID,
                     "instanceID":_loc1_.uInstanceID
                  }));
               }
               else
               {
                  _loc2_ = MissionsListEntry.IsMission(_loc1_);
                  if(_loc2_)
                  {
                     if(_loc1_.bActive)
                     {
                        GlobalFunc.PlayMenuSound(MISSION_TRACKING_TOGGLE_OFF_SOUND);
                     }
                     else
                     {
                        GlobalFunc.PlayMenuSound(MISSION_TRACKING_TOGGLE_ON_SOUND);
                     }
                     this.scrollPositionAtTracking = this.MissionsList_mc.scrollPosition;
                     BSUIDataManager.dispatchEvent(new CustomEvent(MissionMenu_ToggleTrackingQuest,{
                        "questID":_loc1_.uID,
                        "instanceID":_loc1_.uInstanceID
                     }));
                  }
                  else
                  {
                     _loc3_ = this.GetParentMissionData(_loc1_);
                     if(_loc3_)
                     {
                        if(_loc3_.bActive)
                        {
                           GlobalFunc.PlayMenuSound(MISSION_TRACKING_TOGGLE_OFF_SOUND);
                        }
                        else
                        {
                           GlobalFunc.PlayMenuSound(MISSION_TRACKING_TOGGLE_ON_SOUND);
                        }
                        this.scrollPositionAtTracking = this.MissionsList_mc.scrollPosition;
                        BSUIDataManager.dispatchEvent(new CustomEvent(MissionMenu_ToggleTrackingQuest,{
                           "questID":_loc3_.uID,
                           "instanceID":_loc3_.uInstanceID
                        }));
                     }
                  }
               }
            }
         }
      }
      
      private function OnRejectQuest() : void
      {
         var _loc1_:* = undefined;
         if(this.canReject)
         {
            _loc1_ = this.MissionsList_mc.selectedEntry;
            if(_loc1_ != null)
            {
               GlobalFunc.PlayMenuSound(MISSION_TRACKING_TOGGLE_OFF_SOUND);
               this.MissionsList_mc.StoreCurrentListState();
               this.bSkipSelectionSounds = true;
               if(_loc1_.bIsMiscObjective === true)
               {
                  BSUIDataManager.dispatchEvent(new CustomEvent(MissionMenu_RejectQuest,{
                     "questID":_loc1_.uOwnerQuestFormID,
                     "instanceID":_loc1_.uInstanceID
                  }));
               }
               else
               {
                  BSUIDataManager.dispatchEvent(new CustomEvent(MissionMenu_RejectQuest,{
                     "questID":_loc1_.uID,
                     "instanceID":_loc1_.uInstanceID
                  }));
               }
            }
         }
      }
      
      private function onShowButtonBar() : *
      {
         this.ButtonBar_mc.visible = true;
      }
      
      private function SaveMissionMenuState() : *
      {
         var _loc2_:uint = 0;
         BSUIDataManager.dispatchEvent(new Event(MissionMenu_ClearState));
         BSUIDataManager.dispatchEvent(new CustomEvent(MissionMenu_SaveCategoryIndex,{"uValue":this.TabbedFilterSelection_mc.selectedIndex}));
         var _loc1_:Array = this.MissionsList_mc.GetListOfExpandedQuestIds();
         for each(_loc2_ in _loc1_)
         {
            BSUIDataManager.dispatchEvent(new CustomEvent(MissionMenu_SaveOpenedId,{"uValue":_loc2_}));
         }
      }
      
      private function InitializeLastState() : *
      {
         if(!this.InitializedOpenedIds)
         {
            if(this.QuestData != null && this.QuestData.length > 0)
            {
               if(this.StoredLastOpenedIds != null && this.StoredLastOpenedIds.length > 0)
               {
                  this.InitializedOpenedIds = true;
                  this.TabbedFilterSelection_mc.SetSelectedCategoryIndex(this.StoredLastCategory);
                  if(!this.MissionsList_mc.RestorePreviousMissionMenuState(this.StoredLastOpenedIds) && this.TabbedFilterSelection_mc.selectedIndex != 0)
                  {
                     this.TabbedFilterSelection_mc.SetSelectedCategoryIndex(0);
                  }
               }
            }
         }
      }
      
      internal function frame9() : *
      {
         stop();
      }
      
      internal function frame17() : *
      {
         dispatchEvent(new Event("TimelineCloseEvent"));
         stop();
      }
   }
}

