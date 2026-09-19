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
set_version("0.1.0")
set_arch("x64")
set_languages("c++23")
set_encodings("utf-8")
set_warnings("allextra")

add_rules("mode.debug", "mode.releasedbg")

-- 本地 commonlibsf 源码（提供 commonlibsf 静态库目标与 commonlibsf.plugin 规则）
local commonlibsf_dir = path.join(os.projectdir(), "..", "tools", "commonlibsf-main")
includes(commonlibsf_dir)

target("SAQ_ShowAvailableQuests", function()
    set_default(true)
    set_version("0.1.0")
    set_license("GPL-3.0-or-later")

    add_rules("commonlibsf.plugin", {
        name = "Show Available Quests",
        author = "SAQ",
        description = "Adds an 'Available Quests' tab to the vanilla mission menu",
        xse_minimum = "0.2.21"
    })

    add_files("src/**.cpp")
    add_includedirs("src")
    set_pcxxheader("src/PCH.h")
end)
