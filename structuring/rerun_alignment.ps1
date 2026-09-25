# Re-run alignment for the given subjects (default: all), keeping the previous automatic baseline for regression checks,
# then rebuild the audit log.   usage: .\structuring\rerun_alignment.ps1 francais english
param([string[]]$subjects = @("arabe","english","francais","islamic","math","physic","svt"))
$py = ".venv\Scripts\python.exe"
foreach ($s in $subjects) {
  $a = "data\structured\${s}_questions_auto.jsonl"
  if (Test-Path $a) { Copy-Item $a "data\structured\${s}_questions_auto.prev.jsonl" -Force }
}
$env:NO_OVERRIDES = "1"; & $py structuring\align_questions_semantic.py @subjects
Remove-Item Env:\NO_OVERRIDES; & $py structuring\align_questions_semantic.py @subjects
& $py structuring\audit_log_build.py     # always all subjects: the log file is rebuilt as a whole
