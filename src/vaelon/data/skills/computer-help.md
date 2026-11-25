---
name: computer-help
description: Fix and speed up the computer
triggers: компютър, бавен, забива, драйвер, лаптоп, грешка, computer, slow, crash, driver, laptop, error, fix pc
---
1. Diagnose before acting: system_info, list_processes (top memory), security_audit if it smells like malware.
2. Explain the likely cause in plain words, then propose the least risky fix first.
3. Prefer reversible steps; any command goes through run_command (the user approves it).
4. After a fix, measure again to confirm it helped.
