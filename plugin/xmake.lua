-- ============================================================================
--  Starfield Show Available Quests - SFSE plugin (SAQ_ShowAvailableQuests.dll)
--
--  构建：
--      xmake f -y -p windows -a x64 -m releasedbg --vs=2022
--      xmake build SAQ_ShowAvailableQuests
--  （正常情况下不用手动跑，直接 `pwsh tools\build-saq.ps1`）
-- ============================================================================
set_xmakever("3.0.0")

set_project("SAQ_ShowAvailableQuests")
set_version("0.1.10")
set_arch("x64")
set_languages("c++23")
set_encodings("utf-8")
set_warnings("allextra")

add_rules("mode.debug", "mode.releasedbg")

-- 本地 commonlibsf 源码（提供 commonlibsf 静态库目标与 commonlibsf.plugin 规则）
local commonlibsf_dir = path.join(os.projectdir(), "..", "tools", "commonlibsf-main")
includes(commonlibsf_dir)

-- ★★ 第 53 轮（大项 F · 发布就绪）：引擎内 harness 的**编译开关**。
--   为什么要有它：发布给玩家的 DLL 不该包含测试代码（能改任务状态的命令通道、
--   界面测试驱动入口、结果 JSON 落盘……），即使 ini 默认关着也不行 ——
--   Nexus 的包应该是干净的「只做它宣称的事」的产物。
--   · 默认 **开**（y）：日常开发/自测构建（build-saq.ps1 默认）；
--   · 发布包：`xmake f --saq_harness=n` 构建 —— 关掉时
--     SAQ_Test.cpp / SAQ_TestOps.cpp 不参与编译，DLL 里不再有任何 harness 字符串；
--     切回默认：`xmake f --saq_harness=y`（或跑一次 build-saq.ps1）。
--   （tools\package-saq.ps1 会自动完成「切到 n → 构建 → 校验 → 打包」，
--     tools\build-saq.ps1 -Release 是同一件事的构建+部署入口。）
option("saq_harness")
    set_default(true)
    set_showmenu(true)
    set_description("编译引擎内 harness（自动化测试）：开发/自测用；发布包构建应为 n")
option_end()

target("SAQ_ShowAvailableQuests", function()
    set_default(true)
    set_version("0.1.10")
    set_license("GPL-3.0-or-later")

    add_rules("commonlibsf.plugin", {
        name = "Show Available Quests",
        author = "SAQ",
        description = "Adds an 'Available Quests' tab to the vanilla mission menu",
        xse_minimum = "0.2.21"
    })

    add_includedirs("src")
    set_pcxxheader("src/PCH.h")

    -- ★ 第 53 轮：harness 两个翻译单元只在开关打开时编译（关掉 = 从产物里彻底消失）。
    --   ★ 踩过的两个坑（都实测过，别退回去）：
    --     ① 「无条件 remove_files + 条件 add_files 加回」不生效 —— xmake 对同路径的
    --        remove→add 不会恢复（症状：SAQ.cpp 引用了 Test::* 而 SAQ_Test.cpp 没参与
    --        链接 ⇒ LNK2019 三个未解析符号）；
    --     ② `add_files(..., {exclude = ...})` 在当前 xmake 版本下同样不生效
    --        （症状：release 构建里 SAQ_Test.cpp 仍被编译，且它引用了被宏排掉的
    --        UI::InvokeUiTestDrive ⇒ C2039 编译错）。
    --     ⇒ 现在只在**关闭分支**remove；再加上两个 .cpp 自身也用 #if SAQ_WITH_HARNESS
    --       包住（双保险：即使误编译也编成空单元，不会产生链接引用）。
    add_options("saq_harness")
    add_files("src/**.cpp")
    if has_config("saq_harness") then
        add_defines("SAQ_WITH_HARNESS=1")
    else
        add_defines("SAQ_WITH_HARNESS=0")
        remove_files("src/SAQ_Test.cpp", "src/SAQ_TestOps.cpp")
    end
end)

-- ============================================================================
--  ★★ 第 64 轮（大项 K）：**离线层单元测试** target。
--
--  只编译 src/SAQ_Decision.cpp + tests/*.cpp，**不链接 commonlibsf** ——
--  毫秒级、零游戏：过滤 / 门槛 / 候选池 / 引导复算的决策组合在这里枚举断言
--  （见 plugin/tests/SAQ_DecisionTests.cpp 顶部说明）；harness（引擎内用例）
--  覆盖的是「引擎时序」，两者互补。
--
--  跑法（一键）：
--      & ".\tools\test\run-decision-tests.ps1"
--  或手动：
--      cd plugin; xmake build SAQ_Tests; xmake run SAQ_Tests
--
--  说明：本 target 与 DLL target 共用 src/SAQ_Decision.cpp（同一份实现，
--  不是复制品）—— 决策逻辑只有一处，测试测的就是产品用的那份。
-- ============================================================================
target("SAQ_Tests", function()
    set_kind("binary")
    -- 不参与默认构建：build-saq.ps1 显式构建 SAQ_ShowAvailableQuests，
    -- 不受影响；要跑测试显式 `xmake build SAQ_Tests` / `xmake test`。
    set_default(false)
    set_languages("c++23")
    set_encodings("utf-8")
    add_files("src/SAQ_Decision.cpp", "tests/SAQ_DecisionTests.cpp")
    add_includedirs("src", "tests")
    add_tests("default")
end)
