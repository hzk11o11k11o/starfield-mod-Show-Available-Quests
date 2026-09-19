# 后台运行 xEdit 导出 QUST 数据（供 dump_quests.pas 使用）
$root = "d:\workspace\starfield mod\Show Available Quests"
& "$root\tools\run-xedit.ps1" `
  -Exe "d:\workspace\starfield mod\always scan\tools\vendor\xEdit\xSFEdit64.exe" `
  -ScriptPath "$root\tools\xedit-scripts\dump_quests.pas" `
  -PluginList "$root\tools\plugins.txt" `
  -DoneFile "$root\ref\xedit\quests_typed.txt" `
  -LogPath "$root\ref\xedit\xedit.log" `
  *> "$root\ref\xedit\run.log"
