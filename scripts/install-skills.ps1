# Installs every skill in this repo into ~/.claude/skills/ (personal, global
# across all repos/terminals). Safe to re-run - each of our own skill dirs is
# replaced fresh; a same-named dir NOT installed by this repo (no marker
# file) is left alone unless -Force. Also copies agents/*.md and
# agents/hooks/ over ~/.claude/agents/; agents there that aren't in this
# repo are warned about, never deleted. Same for skill dirs in the target
# that carry the marker but are no longer in this repo (stale skills).
#
# Flags:
#   -NoLint     proceed even if no working python 3 is found (skips lint)
#   -Force      replace foreign skill dirs (no marker file) instead of
#               skipping them
#   -NoShCheck  proceed even if Git Bash isn't found. The guard-git hook
#               command in agents/*.md is POSIX sh; without Git Bash, Claude
#               Code can't run it, so the hook blocks nothing (fails open).
#   -Workflow a,b  install only what those sample workflows
#               (site/data/workflows.json) need: their skills, agents and
#               hooks plus dependencies (scripts\workflow_deps.py). Nothing
#               outside the selection is touched or warned about. Hooks are
#               copied to $env:CLAUDE_HOOKS_DIR (default: hooks\ next to the
#               skills dir) and their settings.json snippet printed, never
#               wired. Needs python 3, even with -NoLint.
#   -ListWorkflows  print the workflow names and exit
#   -Skill a,b  install only those skills, agents or hooks plus what they
#               need, same rules as -Workflow; combines with -Workflow
#               (union).
#   -ListSkills  print every skill, agent and hook name and exit
param(
    [switch]$NoLint,
    [switch]$Force,
    [switch]$NoShCheck,
    [string[]]$Workflow,
    [switch]$ListWorkflows,
    [string[]]$Skill,
    [switch]$ListSkills
)
$ErrorActionPreference = "Stop"

$Marker = ".from-krishp147-skills"

$repoRoot = Split-Path -Parent $PSScriptRoot
$target = if ($env:CLAUDE_SKILLS_DIR) { $env:CLAUDE_SKILLS_DIR } else { Join-Path $env:USERPROFILE ".claude\skills" }
$agentsTarget = if ($env:CLAUDE_AGENTS_DIR) { $env:CLAUDE_AGENTS_DIR } else { Join-Path $env:USERPROFILE ".claude\agents" }

function Get-WorkingPython3 {
    # first candidate that actually runs Python 3. The probe skips the
    # Windows Store python stub (WindowsApps alias that refuses to run
    # code) while keeping a real Store-installed Python, which lives there too.
    $candidates = @(
        @{ Cmd = "python"; Args = @() },
        @{ Cmd = "python3"; Args = @() },
        @{ Cmd = "py"; Args = @("-3") }
    )
    foreach ($c in $candidates) {
        $cmd = Get-Command $c.Cmd -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        try {
            & $cmd.Source @($c.Args) -c "import sys;sys.exit(0 if sys.version_info[0]==3 else 1)" 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) {
                return [PSCustomObject]@{ Path = $cmd.Source; Args = $c.Args }
            }
        } catch {
            continue
        }
    }
    return $null
}

$py = Get-WorkingPython3
$deps = Join-Path $repoRoot "scripts\workflow_deps.py"
if ($ListWorkflows) {
    if (-not $py) {
        [Console]::Error.WriteLine("error: -ListWorkflows needs python 3 (checked python, python3, py -3).")
        exit 1
    }
    & $py.Path @($py.Args) $deps list
    exit $LASTEXITCODE
}
if ($ListSkills) {
    if (-not $py) {
        [Console]::Error.WriteLine("error: -ListSkills needs python 3 (checked python, python3, py -3).")
        exit 1
    }
    & $py.Path @($py.Args) $deps list-names
    exit $LASTEXITCODE
}

function Find-GitBash {
    # Where Claude Code gets a POSIX shell on Windows: CLAUDE_CODE_GIT_BASH_PATH,
    # else sh/bash on PATH, else bash.exe in the Git for Windows install.
    # System32 bash.exe is the WSL launcher, not Git Bash, so it doesn't count.
    if ($env:CLAUDE_CODE_GIT_BASH_PATH -and (Test-Path -LiteralPath $env:CLAUDE_CODE_GIT_BASH_PATH -PathType Leaf)) {
        return $env:CLAUDE_CODE_GIT_BASH_PATH
    }
    foreach ($name in @("sh", "bash")) {
        foreach ($cmd in @(Get-Command $name -CommandType Application -ErrorAction SilentlyContinue)) {
            if ($cmd.Source -and $cmd.Source -notmatch '\\(System32|SysWOW64|WindowsApps)\\') {
                return $cmd.Source
            }
        }
    }
    $git = Get-Command git -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($git -and $git.Source) {
        $gitDir = Split-Path -Parent $git.Source
        foreach ($rel in @("..\bin\bash.exe", "bash.exe", "..\usr\bin\bash.exe", "..\..\bin\bash.exe")) {
            $cand = Join-Path $gitDir $rel
            if (Test-Path -LiteralPath $cand -PathType Leaf) {
                return (Resolve-Path -LiteralPath $cand).Path
            }
        }
    }
    return $null
}

# Check before copying anything: guard-git's hook command is POSIX sh.
$gitBash = Find-GitBash
if (-not $gitBash) {
    if ($NoShCheck) {
        Write-Warning "Git Bash not found - guard-git hook won't run and blocks nothing (-NoShCheck)"
    } else {
        [Console]::Error.WriteLine("error: Git Bash not found (checked CLAUDE_CODE_GIT_BASH_PATH, sh/bash on PATH, bash.exe in the git install).")
        [Console]::Error.WriteLine("The guard-git hook command is POSIX sh; without Git Bash Claude Code can't run")
        [Console]::Error.WriteLine("the hook, which then fails open (blocks nothing). Install Git for Windows,")
        [Console]::Error.WriteLine("set CLAUDE_CODE_GIT_BASH_PATH to its bash.exe, or pass -NoShCheck to install anyway.")
        exit 1
    }
}

if ($py) {
    # lint WARN lines go to stderr; under "Stop", PS 5.1 turns redirected
    # native stderr into a terminating error, so relax it for this call.
    $ErrorActionPreference = "Continue"
    & $py.Path @($py.Args) (Join-Path $repoRoot "scripts\lint.py")
    $lintExit = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    if ($lintExit -ne 0) {
        Write-Error "lint failed - aborting install"
        exit 1
    }
} elseif ($NoLint) {
    Write-Warning "no working python 3 found, skipping lint (-NoLint)"
} else {
    Write-Error "no working python 3 found on PATH (checked python, python3, py -3). Install Python 3, or pass -NoLint to skip the lint step."
    exit 1
}

# -Workflow / -Skill: resolve before creating or copying anything; an
# unknown name makes the resolver list the valid names and exit non-zero.
$partial = $PSBoundParameters.ContainsKey("Workflow") -or $PSBoundParameters.ContainsKey("Skill")
$selSkills = @()
$selAgents = @()
$selHooks = @()
$agentHooks = $false
$wfNames = @()
$skillNames = @()
if ($partial) {
    $wfNames = @($Workflow | ForEach-Object { "$_" -split "," } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    $skillNames = @($Skill | ForEach-Object { "$_" -split "," } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    if (-not $py) {
        [Console]::Error.WriteLine("error: -Workflow and -Skill need python 3 to resolve what to install (checked python, python3, py -3).")
        [Console]::Error.WriteLine("Install Python 3; -NoLint does not skip this step.")
        exit 1
    }
    $ErrorActionPreference = "Continue"
    $resolveArgs = @($wfNames)
    foreach ($n in $skillNames) { $resolveArgs += @("--skill", $n) }
    $resolved = @(& $py.Path @($py.Args) $deps resolve @resolveArgs)
    $resolveExit = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    if ($resolveExit -ne 0) { exit $resolveExit }
    foreach ($raw in $resolved) {
        $line = "$raw".TrimEnd("`r")
        if ($line -like "skill *") { $selSkills += $line.Substring(6) }
        elseif ($line -like "agent *") { $selAgents += $line.Substring(6) }
        elseif ($line -like "hook *") { $selHooks += $line.Substring(5) }
        elseif ($line -eq "agent-hooks") { $agentHooks = $true }
        elseif ($line) {
            [Console]::Error.WriteLine("error: unexpected resolver output: $line")
            exit 1
        }
    }
}

if ((-not $partial) -or $selSkills.Count -gt 0) {
    New-Item -ItemType Directory -Force -Path $target | Out-Null
}
if ((-not $partial) -or $selAgents.Count -gt 0) {
    New-Item -ItemType Directory -Force -Path $agentsTarget | Out-Null
}

$templatesPath = Join-Path $repoRoot "templates"
$installed = @()
$skippedForeign = @()
$repoSkills = @()
function Install-Skill($skillDir) {
    $name = $skillDir.Name
    $dest = Join-Path $target $name
    $script:repoSkills += $name
    if ((Test-Path $dest) -and -not (Test-Path (Join-Path $dest $Marker)) -and -not $Force) {
        Write-Warning "$dest exists and wasn't installed by this repo, skipping (use -Force to replace)"
        $script:skippedForeign += $name
        return
    }
    if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
    Copy-Item -Recurse $skillDir.FullName $dest
    Get-ChildItem -Path $dest -Recurse -Filter "__pycache__" -Directory -ErrorAction SilentlyContinue |
        ForEach-Object { Remove-Item -Recurse -Force $_.FullName }
    New-Item -ItemType File -Force -Path (Join-Path $dest $Marker) | Out-Null
    $script:installed += $name
}

$installedAgents = @()
function Install-Agent($agentFile) {
    $dest = Join-Path $agentsTarget $agentFile.Name
    Copy-Item -Force $agentFile.FullName $dest
    $script:installedAgents += [System.IO.Path]::GetFileNameWithoutExtension($agentFile.Name)
}

function Install-AgentHooks {
    $hooksSrc = Join-Path $repoRoot "agents\hooks"
    $hooksDest = Join-Path $agentsTarget "hooks"
    if (Test-Path $hooksSrc) {
        New-Item -ItemType Directory -Force -Path $hooksDest | Out-Null
        Copy-Item -Force -Recurse (Join-Path $hooksSrc "*") $hooksDest
        Get-ChildItem -Path $hooksDest -Recurse -Filter "__pycache__" -Directory -ErrorAction SilentlyContinue |
            ForEach-Object { Remove-Item -Recurse -Force $_.FullName }
    }
}

if ($partial) {
    foreach ($d in $selSkills) { Install-Skill (Get-Item -LiteralPath (Join-Path $repoRoot $d)) }
    foreach ($a in $selAgents) { Install-Agent (Get-Item -LiteralPath (Join-Path $repoRoot "agents\$a.md")) }
    if ($agentHooks) { Install-AgentHooks }

    # hooks\<name>.py: copied, never wired into settings.json. A different
    # file already there is left alone unless -Force.
    $hooksTarget = if ($env:CLAUDE_HOOKS_DIR) { $env:CLAUDE_HOOKS_DIR } else { Join-Path (Split-Path -Parent $target) "hooks" }
    $copiedHooks = @()
    $skippedHooks = @()
    foreach ($h in $selHooks) {
        $src = Join-Path $repoRoot "hooks\$h.py"
        $dest = Join-Path $hooksTarget "$h.py"
        if ((Test-Path -LiteralPath $dest) -and -not $Force -and
            (Get-FileHash -LiteralPath $src).Hash -ne (Get-FileHash -LiteralPath $dest).Hash) {
            Write-Warning "$dest exists and differs from this repo's copy, skipping (use -Force to replace)"
            $skippedHooks += $h
            continue
        }
        New-Item -ItemType Directory -Force -Path $hooksTarget | Out-Null
        Copy-Item -Force -LiteralPath $src -Destination $dest
        $copiedHooks += $h
    }

    if ($wfNames.Count -gt 0) { Write-Host "Workflow(s): $($wfNames -join ' ')" }
    if ($skillNames.Count -gt 0) { Write-Host "Skill(s): $($skillNames -join ' ')" }
    if ($selSkills.Count -gt 0) {
        Write-Host "Installed $($installed.Count) skill(s) to $target :"
        $installed | ForEach-Object { Write-Host "  - $_" }
    }
    if ($skippedForeign.Count -gt 0) {
        Write-Warning "skipped $($skippedForeign.Count) foreign skill dir(s) without marker (use -Force): $($skippedForeign -join ', ')"
    }
    if ($installedAgents.Count -gt 0) {
        Write-Host "Installed $($installedAgents.Count) agent(s) to $agentsTarget (with the guard-git hook in hooks\):"
        $installedAgents | ForEach-Object { Write-Host "  - $_" }
    }
    if ($copiedHooks.Count -gt 0) {
        Write-Host "Copied $($copiedHooks.Count) hook(s) to $hooksTarget, NOT wired. To enable, add this to the `"hooks`" block of ~/.claude/settings.json (see hooks/README.md):"
        & $py.Path @($py.Args) $deps snippet $hooksTarget @copiedHooks | ForEach-Object { Write-Host $_ }
    }
    if ($skippedForeign.Count -gt 0 -or $skippedHooks.Count -gt 0) {
        exit 1
    }
    exit 0
}

Get-ChildItem -Path $repoRoot -Recurse -Filter "SKILL.md" -Depth 2 | Where-Object {
    -not $_.FullName.StartsWith($templatesPath + [System.IO.Path]::DirectorySeparatorChar)
} | ForEach-Object { Install-Skill $_.Directory }

Get-ChildItem -Path (Join-Path $repoRoot "agents") -Filter "*.md" -File | Where-Object { $_.Name -ne "README.md" } | ForEach-Object {
    Install-Agent $_
}

Install-AgentHooks

Write-Host "Installed $($installed.Count) skill(s) to $target :"
$installed | ForEach-Object { Write-Host "  - $_" }

if ($skippedForeign.Count -gt 0) {
    Write-Warning "skipped $($skippedForeign.Count) foreign skill dir(s) without marker (use -Force): $($skippedForeign -join ', ')"
}

Write-Host "Installed $($installedAgents.Count) agent(s) to $agentsTarget :"
$installedAgents | ForEach-Object { Write-Host "  - $_" }

$agentsSrc = Join-Path $repoRoot "agents"
$stale = @(Get-ChildItem -Path $agentsTarget -Filter "*.md" -File | Where-Object {
    $_.Name -ne "README.md" -and -not (Test-Path (Join-Path $agentsSrc $_.Name))
} | ForEach-Object { $_.Name })
if ($stale.Count -gt 0) {
    Write-Warning "stale agent(s) not in repo, remove manually: $($stale -join ', ')"
}

$staleSkills = @(Get-ChildItem -LiteralPath $target -Directory -Force | Where-Object {
    (Test-Path -LiteralPath (Join-Path $_.FullName $Marker) -PathType Leaf) -and ($repoSkills -notcontains $_.Name)
} | ForEach-Object { $_.Name })
if ($staleSkills.Count -gt 0) {
    Write-Warning "stale skill(s) not in repo, remove manually: $($staleSkills -join ', ')"
}

if ($skippedForeign.Count -gt 0) {
    exit 1
}
# explicit success code: callers using `& install-skills.ps1` read
# $LASTEXITCODE, which otherwise holds the last native exit (e.g. a failed
# python probe when -NoLint is used).
exit 0
