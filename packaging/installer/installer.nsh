!macro customInit
  InitPluginsDir
  File /oname=$PLUGINSDIR\nsis_stop_memo.ps1 "${PROJECT_DIR}\installer\nsis_stop_memo.ps1"
  nsExec::ExecToLog 'powershell -NoProfile -ExecutionPolicy Bypass -File "$PLUGINSDIR\nsis_stop_memo.ps1" -Mode Detect -Flag "$PLUGINSDIR\memo-running.flag"'
  IfFileExists "$PLUGINSDIR\memo-running.flag" 0 memo_no_running
    MessageBox MB_ICONEXCLAMATION|MB_YESNO "检测到 Memo 或 Memo 后台服务正在运行。为了避免安装失败，需要先结束旧版本进程，然后继续安装。是否现在结束这些进程？" IDYES memo_kill_running IDNO memo_abort_install
    memo_abort_install:
      Abort "请先关闭 Memo 后再重新运行安装程序。"
    memo_kill_running:
      nsExec::ExecToLog 'powershell -NoProfile -ExecutionPolicy Bypass -File "$PLUGINSDIR\nsis_stop_memo.ps1" -Mode Kill'
  memo_no_running:
!macroend
