# Installs every skill in this repo into ~/.claude/skills/ (personal, global
# across all repos/terminals). Safe to re-run - each of our own skill dirs is
# replaced fresh; a same-named dir NOT installed by this repo (no marker
# file) is left alone unless -Force. Also copies agents/*.md and
# agents/hooks/ over ~/.claude/agents/; agents there that aren't in this
# repo are warned about, never deleted.
#
# Flags:
#   -NoLint     proceed even if no working python 3 is found (skips lint)
#   -Force      replace foreign skill dirs (no marker file) instead of
#               skipping them
#   -NoShCheck  proceed even if Git Bash isn't found. The guard-git hook
#               command in agents/*.md is POSIX sh; without Git Bash, Claude
#               Code can't run it, so the hook blocks nothing (fails open).
param(
    [switch]$NoLint,
    [switch]$Force,
    [switch]$NoShCheck
)
$ErrorActionPreference = "Stop"

$Marker = ".from-krishp147-skills"

$repoRoot = Split-Path -Parent $PSScriptRoot
$target = if ($env:CLAUDE_SKILLS_DIR) { $env:CLAUDE_SKILLS_DIR } else { Join-Path $env:USERPROFILE ".claude\skills" }
$agentsTarget = if ($env:CLAUDE_AGENTS_DIR) { $env:CLAUDE_AGENTS_DIR } else { Join-Path $env:USERPROFILE ".claude\agents" }

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

New-Item -ItemType Directory -Force -Path $target | Out-Null
New-Item -ItemType Directory -Force -Path $agentsTarget | Out-Null

$templatesPath = Join-Path $repoRoot "templates"
$installed = @()
$skippedForeign = @()
Get-ChildItem -Path $repoRoot -Recurse -Filter "SKILL.md" -Depth 2 | Where-Object {
    -not $_.FullName.StartsWith($templatesPath + [System.IO.Path]::DirectorySeparatorChar)
} | ForEach-Object {
    $skillDir = $_.Directory
    $name = $skillDir.Name
    $dest = Join-Path $target $name
    if ((Test-Path $dest) -and -not (Test-Path (Join-Path $dest $Marker)) -and -not $Force) {
        Write-Warning "$dest exists and wasn't installed by this repo, skipping (use -Force to replace)"
        $skippedForeign += $name
        return
    }
    if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
    Copy-Item -Recurse $skillDir.FullName $dest
    Get-ChildItem -Path $dest -Recurse -Filter "__pycache__" -Directory -ErrorAction SilentlyContinue |
        ForEach-Object { Remove-Item -Recurse -Force $_.FullName }
    New-Item -ItemType File -Force -Path (Join-Path $dest $Marker) | Out-Null
    $installed += $name
}

$installedAgents = @()
Get-ChildItem -Path (Join-Path $repoRoot "agents") -Filter "*.md" -File | Where-Object { $_.Name -ne "README.md" } | ForEach-Object {
    $dest = Join-Path $agentsTarget $_.Name
    Copy-Item -Force $_.FullName $dest
    $installedAgents += [System.IO.Path]::GetFileNameWithoutExtension($_.Name)
}

$hooksSrc = Join-Path $repoRoot "agents\hooks"
$hooksDest = Join-Path $agentsTarget "hooks"
if (Test-Path $hooksSrc) {
    New-Item -ItemType Directory -Force -Path $hooksDest | Out-Null
    Copy-Item -Force -Recurse (Join-Path $hooksSrc "*") $hooksDest
    Get-ChildItem -Path $hooksDest -Recurse -Filter "__pycache__" -Directory -ErrorAction SilentlyContinue |
        ForEach-Object { Remove-Item -Recurse -Force $_.FullName }
}

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

if ($skippedForeign.Count -gt 0) {
    exit 1
}
