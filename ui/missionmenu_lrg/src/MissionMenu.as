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
      
      private var SaqTabProbe:String = "-";

      private var SaqOurTabProbe:String = "-";

      private var SaqOurTabMaxList:int = -1;

      // ★ 第 19 轮：最近一次 FilterKnownQuests 过滤掉的「玩家已有」uID 名单（日志诊断用）。
      private var SaqDropList:String = "-";

      private var SaqDropCount:int = 0;

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
         var _loc2_:Object = {};
         if(this.QuestData != null)
         {
            var _loc3_:int = 0;
            while(_loc3_ < this.QuestData.length)
            {
               _loc2_[this.QuestData[_loc3_].uID] = true;
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
         while(_loc5_ < param1.length)
         {
            if(!_loc2_[param1[_loc5_].uID])
            {
               _loc4_.push(param1[_loc5_]);
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
                  //   有了它，「设定航线」才能走原版的星图流程（见 SaqPlotToLocationViaEngine）。
                  //   旧载荷没有这一行 ⇒ 保持 0（功能降级，不报错）。
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
                        "bSaqHasTarget":_loc7_.length >= 5 ? _loc7_[4] == "1" : true
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
      // 原始类型 -> UI 能安全渲染的类型。
      // 原版 QuestUtils.GetQuestIconLabel 只对「活动(0)/杂项(3)/任务(4)」返回真实图标名，
      // 派系(2)/主线(1) 会落到 default -> "None"，而 FactionSymbols 里未必有 "None" 这一帧
      // —— gotoAndStop 找不到帧会抛异常，把整行（甚至整列表）的渲染带崩。
      // 静态表里存在的就是 0/2/3/4，所以只把 2 归一成 4（派系任务按「任务」图标显示）。
      private static function SaqSafeType(param1:int) : int
      {
         if(param1 == QuestUtils.ACTIVITY_QUEST_TYPE || param1 == QuestUtils.MISC_QUEST_TYPE || param1 == QuestUtils.MISSION_QUEST_TYPE)
         {
            return param1;
         }
         return QuestUtils.MISSION_QUEST_TYPE;
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
            "iFaction":FactionUtils.FACTION_NONE,
            // ★ 第 27 轮：入口条目（任务板）的子项名不同 —— 它不是「任务」而是「入口」。
            "sName":param1.iType == SAQ_ENTRY_TYPE
               ? (this.SaqUseChinese() ? "前往任务板" : "Go to the mission board")
               : (this.SaqUseChinese() ? "前往接取地点" : "Reach the pickup location"),
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
      
      // 右侧详情面板里的描述文案（固定内容，告诉玩家这条记录怎么用）。
      // ★ 第 27 轮：第 2 个参数 = 入口条目（任务板）—— 它没有「接取地点」的概念，
      //   描述改成「这是什么、怎么去」。
      private function SaqDescriptionText(param1:Boolean, param2:Boolean = false) : String
      {
         // ★ 第 27 轮：无限任务入口（任务板）。
         // ★ 第 29 轮：入口引用已经在 ESM 里 override 成**常驻引用**（任何位置都能取到），
         //   所以这个「取不到」分支只是兜底（ESM 没加载 / 被别的插件覆盖掉时）。
         //   措辞不再提「太远」——玩家明确反馈「不该存在太远就不能导航」。
         if(param2 == true)
         {
            if(param1 != true)
            {
               return this.SaqUseChinese()
                  ? "暂时无法导航 —— 这个位置此刻取不到（多半是所在区域还没加载出来）。稍后重新打开一次任务菜单再试。"
                  : "Cannot navigate right now - the location is not available at the moment (its area has not loaded yet). Reopen the mission menu and try again.";
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
         // ★ 第 23 轮：没有引导目标的任务（261 条里 52 条）——列表照常显示，但**无法导航**。
         //   把原因直接写进描述，玩家不用点一下才知道（此前「点了瞬间回滚」看不出原因）。
         if(param1 != true)
         {
            return this.SaqUseChinese()
               ? "这条任务当前可以接取，但还没有导航目标 —— 暂时无法引导到接取地点（任务本身照常显示）。"
               : "This quest is available, but it has no navigation target yet - it cannot guide you to the pickup location.";
         }
         var _loc1_:String = this.SaqCourseKeyName();
         if(_loc1_.length == 0)
         {
            return this.SaqUseChinese()
               ? "这条任务当前可以接取。展开后选中目标，或使用底部的「设定航线」即可引导到接取地点。"
               : "This quest is currently available. Expand it, then select the objective or use SET COURSE to be guided to the pickup location.";
         }
         return this.SaqUseChinese()
            ? "这条任务当前可以接取。展开后选中目标，或按 " + _loc1_ + "（设定航线）即可引导到接取地点。"
            : "This quest is currently available. Expand it, then select the objective or press " + _loc1_ + " (SET COURSE) to be guided to the pickup location.";
      }
      
      private function SaqBuildEntry(param1:Object) : Object
      {
         return {
            "uID":param1.uID,
            "uInstanceID":0,
            "iType":SaqSafeType(param1.iType),
            "iFaction":FactionUtils.FACTION_NONE,
            "sName":this.SaqUseChinese() ? param1.sNameZh : param1.sNameEn,
            // ★ 第 27 轮：入口条目（任务板）的描述用专门文案（第 2 个参数）。
            "sDescription":this.SaqDescriptionText(param1.bSaqHasTarget != false, param1.iType == SAQ_ENTRY_TYPE),
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
            }
         }
         catch(e:Error)
         {
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
         return _loc8_;
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
         return "0x" + Number(param1.uID).toString(16) + "@" + _loc1_;
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
      private function SaqQuestName(param1:Object) : String
      {
         if(param1 == null)
         {
            return "?";
         }
         if(MissionsListEntry.IsMission(param1))
         {
            return param1.sName;
         }
         var _loc2_:Object = this.FindQuestEntryByID(this.AvailableQuests, param1.uID);
         return _loc2_ != null ? _loc2_.sName : param1.sName;
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
            if(param1.iType == SAQ_ENTRY_TYPE)
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
      //  ★ 第 36 轮：SET COURSE 的「原版星图」这一半
      //
      //  原版（真实任务）按 R 时做的事情：dispatch MissionMenu_PlotToLocation{questID} →
      //  引擎取该任务的目标位置 → 目标不在当前星球就**打开星图**、聚焦到那颗星球，
      //  并询问玩家是否导航；在同一星球上则直接设置本地航线。
      //
      //  第 36 轮的设想：把**代理任务**（SAQ_MainQuest，真实任务、目标别名绑着接取地点）
      //  的 FormID 丢进同一条流程，效果就与原版一致。
      //
      //  ★ 第 37 轮实测更正：**这条 dispatch 在引擎里没有任何处理** —— 离线复核证明
      //   `BSTGlobalEvent::EventSource<MissionMenu_PlotToLocation>` 在整个 exe 里除了
      //   它自己的静态初始化之外没有任何引用（= 没有 C++ sink；同族的
      //   MissionMenu_ShowItemLocation / DataMenu_PlotToLocation 也一样）。所以这里
      //   照抄原版是死路，星图改由 **DLL + Papyrus 脚本**实现（见 SAQ.cpp 的
      //   RequestStarMapOpen / SAQ_Main.psc 的 OpenStarMapFor，docs/05 第十一节）：
      //     DLL 把 GuideState 置 5 并用 UI 消息关掉任务菜单 → 脚本在「菜单关闭」事件里
      //     应用引导并调用 Game.ShowGalaxyStarMapMenuAndPlotToLocation(地点)。
      //   本函数保留下来：① 与未来版本对齐（若某个版本真注册了 sink，这里立刻有用）；
      //   ② `星图:已请求(代理任务 0x…)` 这行 note 是日志里的链路证据。
      //
      //  代理任务的运行期 FormID 只有 C++ 侧知道（插件加载前缀是运行期的），由载荷的
      //  `P\t<FormID>` 行推来（见 SAQ_UI.cpp::BuildPayloadUtf8 / SaqParsePayload）。
      //  拿不到（内嵌回退表 / 旧 DLL）就静默跳过 —— 只保留我们自己的引导，不报错。
      //
      //  返回值只用于日志（SAQ_Report 的 guide 段）。
      // ==================================================================
      private function SaqPlotToLocationViaEngine() : Boolean
      {
         if(Number(this.SaqProxyQuestID) <= 0)
         {
            this.SaqGuideNote += "｜星图:无代理任务ID";
            return false;
         }
         try
         {
            BSUIDataManager.dispatchEvent(new CustomEvent(MissionMenu_PlotToLocation,{
               "questID":this.SaqProxyQuestID,
               "objectiveID":-1
            }));
            GlobalFunc.PlayMenuSound(MISSION_SHOW_ON_MAP_SOUND);
            this.SaqGuideNote += "｜星图:已请求(代理任务 0x" + Number(this.SaqProxyQuestID).toString(16) + ")";
            return true;
         }
         catch(_loc1_:Error)
         {
            // 引擎拒绝（例如任务菜单要关了）时不要让异常冒出去把菜单带崩。
            this.SaqGuideNote += "｜星图:异常 " + _loc1_.message;
            return false;
         }
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

      // ★ 第 38 轮：C++ 回写成功后的「关菜单」这一步（见 SaqPendingCloseToGame 的说明）。
      //   `CloseMenu(true)` = 原版「退回游戏」路径：
      //     设置 bReturningToGame → StartGameRender + DataMenu_SetMenuForQuickEntry
      //     → 播关闭动画 → OnTimelineCloseEvent → SaveMissionMenuState + GlobalFunc.CloseAllMenus()
      //   整个暂停菜单随之关掉 —— 游戏恢复运行，脚本的定时器 0.5 秒后走到、星图打开。
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
      private function SaqQuestNameByID(param1:Number) : String
      {
         var _loc2_:Object = this.FindQuestEntryByID(this.AvailableQuests, param1);
         if(_loc2_ != null)
         {
            return _loc2_.sName;
         }
         return "?";
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
            var _loc2_:Boolean = this.SaqToggleGuide(_loc1_, true, false);
            if(_loc2_)
            {
               this.SaqPlotToLocationViaEngine();
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

