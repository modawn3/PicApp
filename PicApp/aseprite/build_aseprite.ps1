# Aseprite 를 승진님 PC 에서 소스로 빌드한다 (개인용. 빌드한 exe 는 다른 사람에게 나눠 주면 안 됨: Aseprite EULA).
# Aseprite_빌드.bat 이 이 파일을 실행한다. 다시 실행하면 새 정식판이 있을 때만 받아서 다시 빌드한다.
#
# 만드는 폴더 (기본 C:\AI-PIC\Aseprite):
#   src\    Aseprite 소스 (정식판 태그)
#   deps\   Skia (Aseprite 가 쓰는 그림 라이브러리, 미리 빌드된 것)
#   tools\  CMake, Ninja, (없으면) Git — 설치하지 않고 폴더에만 둠
#   build\  빌드 결과. 실행 파일은 build\bin\aseprite.exe
#
# 공식 안내: https://github.com/aseprite/aseprite/blob/main/INSTALL.md (Windows 부분을 그대로 자동화)

param(
    [string]$Root = "C:\AI-PIC\Aseprite",
    [string]$Version = "",      # 예: v1.3.18.6. 비우면 최신 정식판
    [switch]$Fresh              # 빌드 폴더를 지우고 처음부터
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # 다운로드 진행 표시가 PowerShell 5 에서 매우 느려서 끔
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$CMakeVer = "3.31.6"
$NinjaVer = "1.12.1"
$MinGitVer = "2.47.1"
$Repo = "https://github.com/aseprite/aseprite.git"

function Say($msg, $color = "White") { Write-Host $msg -ForegroundColor $color }
function Step($n, $msg) { Write-Host ""; Write-Host "[$n/7] $msg" -ForegroundColor Cyan }
function Fail($msg) {
    Write-Host ""
    Write-Host "멈췄어요: $msg" -ForegroundColor Red
    Write-Host "자세한 기록: $Root\build_log.txt" -ForegroundColor Yellow
    try { Stop-Transcript | Out-Null } catch {}
    exit 1
}
function Download($url, $out) {
    Say "  받는 중: $url" "DarkGray"
    for ($i = 1; $i -le 3; $i++) {
        try { Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing; return }
        catch { if ($i -eq 3) { throw }; Start-Sleep -Seconds (3 * $i) }
    }
}
function Unzip($zip, $dest) {
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    $tar = Join-Path $env:SystemRoot "System32\tar.exe"
    if (Test-Path $tar) { & $tar -xf $zip -C $dest; if ($LASTEXITCODE -eq 0) { return } }
    Expand-Archive -Path $zip -DestinationPath $dest -Force
}

trap { Fail "$_" }

New-Item -ItemType Directory -Force -Path $Root, "$Root\tools", "$Root\deps" | Out-Null
try { Start-Transcript -Path "$Root\build_log.txt" -Force | Out-Null } catch {}

Say "==============================================================" "Cyan"
Say " Aseprite 자동 빌드 (개인용)" "Cyan"
Say " 폴더: $Root" "Cyan"
Say " 처음에는 준비물 설치 + 빌드로 1~2시간 걸릴 수 있어요." "Cyan"
Say " 노트북은 충전기를 꽂아 두세요. 중간에 창을 닫지 마세요." "Cyan"
Say "==============================================================" "Cyan"

# ---------------------------------------------------------------- 1. 디스크
Step 1 "디스크 빈 공간 확인"
$drive = (Get-Item $Root).PSDrive
$freeGB = [math]::Round($drive.Free / 1GB, 1)
Say "  $($drive.Name): 드라이브 빈 공간 $freeGB GB"
$vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
$needGB = 6
if (-not (Test-Path $vswhere)) { $needGB = 15 }
if ($freeGB -lt $needGB) { Fail "빈 공간이 $needGB GB 이상 필요해요. 필요 없는 파일을 지우고 다시 실행하세요." }

# ---------------------------------------------------------------- 2. Visual Studio C++ 도구
Step 2 "C++ 빌드 도구 (Visual Studio 2022 Build Tools) 확인"
function Find-VC {
    if (-not (Test-Path $vswhere)) { return $null }
    $p = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    if ($p -and (Test-Path (Join-Path $p "VC\Auxiliary\Build\vcvars64.bat"))) { return $p }
    return $null
}
function Has-SDK { return [bool](Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\Include\10.*" -ErrorAction SilentlyContinue) }

$vs = Find-VC
if (-not $vs -or -not (Has-SDK)) {
    Say "  C++ 빌드 도구가 없어서 설치할게요 (약 7~10GB, 20~40분)." "Yellow"
    Say "  '이 앱이 디바이스를 변경하도록 허용하시겠어요?' 창이 뜨면 [예] 를 눌러 주세요." "Yellow"
    $boot = "$Root\tools\vs_BuildTools.exe"
    Download "https://aka.ms/vs/17/release/vs_BuildTools.exe" $boot
    $p = Start-Process -FilePath $boot -Wait -PassThru -ArgumentList @(
        "--passive", "--wait", "--norestart", "--nocache",
        "--add", "Microsoft.VisualStudio.Workload.VCTools", "--includeRecommended")
    if ($p.ExitCode -eq 3010) { Say "  설치는 됐고, 나중에 PC 를 다시 시작하라고 하네요. 빌드는 계속할게요." "Yellow" }
    elseif ($p.ExitCode -ne 0) { Fail "C++ 빌드 도구 설치가 끝나지 않았어요 (코드 $($p.ExitCode)). [예] 를 눌렀는지 확인하고 다시 실행하세요." }
    $vs = Find-VC
    if (-not $vs) { Fail "C++ 빌드 도구를 찾지 못했어요. PC 를 다시 시작한 뒤 다시 실행해 보세요." }
}
Say "  찾음: $vs" "Green"

# ---------------------------------------------------------------- 3. Git, CMake, Ninja
Step 3 "Git, CMake, Ninja 준비 (설치 없이 tools 폴더에만)"
$git = (Get-Command git.exe -ErrorAction SilentlyContinue).Source
if (-not $git) { foreach ($c in @("$env:ProgramFiles\Git\cmd\git.exe", "$Root\tools\git\cmd\git.exe")) { if (Test-Path $c) { $git = $c; break } } }
if (-not $git) {
    $z = "$Root\tools\mingit.zip"
    Download "https://github.com/git-for-windows/git/releases/download/v$MinGitVer.windows.1/MinGit-$MinGitVer-64-bit.zip" $z
    Unzip $z "$Root\tools\git"; Remove-Item $z
    $git = "$Root\tools\git\cmd\git.exe"
}
$cmakeDir = "$Root\tools\cmake-$CMakeVer-windows-x86_64\bin"
if (-not (Test-Path "$cmakeDir\cmake.exe")) {
    $z = "$Root\tools\cmake.zip"
    Download "https://github.com/Kitware/CMake/releases/download/v$CMakeVer/cmake-$CMakeVer-windows-x86_64.zip" $z
    Unzip $z "$Root\tools"; Remove-Item $z
}
$ninjaDir = "$Root\tools\ninja-$NinjaVer"
if (-not (Test-Path "$ninjaDir\ninja.exe")) {
    $z = "$Root\tools\ninja.zip"
    Download "https://github.com/ninja-build/ninja/releases/download/v$NinjaVer/ninja-win.zip" $z
    Unzip $z $ninjaDir; Remove-Item $z
}
Say "  git: $git" "Green"
Say "  cmake: $cmakeDir" "Green"
Say "  ninja: $ninjaDir" "Green"

# ---------------------------------------------------------------- 4. 소스
Step 4 "Aseprite 소스 받기"
if (-not $Version) {
    $tags = & $git ls-remote --tags --refs --sort=-v:refname $Repo "v1.*"
    if ($LASTEXITCODE -ne 0) { Fail "GitHub 에 연결하지 못했어요. 인터넷을 확인하세요." }
    $Version = ($tags | ForEach-Object { ($_ -split "refs/tags/")[1] } |
                Where-Object { $_ -notmatch "beta|rc|dev|alpha" } | Select-Object -First 1)
    if (-not $Version) { Fail "최신 정식판 번호를 찾지 못했어요." }
}
Say "  버전: $Version"
$src = "$Root\src"
$have = ""
if (Test-Path "$src\.picapp_version") { $have = (Get-Content "$src\.picapp_version" -Raw).Trim() }
if ($have -ne $Version) {
    if (Test-Path $src) { Say "  예전 소스($have)를 지우고 새로 받아요."; Remove-Item -Recurse -Force $src }
    & $git -c core.longpaths=true -c advice.detachedHead=false clone --depth 1 --branch $Version `
        --recursive --shallow-submodules $Repo $src
    if ($LASTEXITCODE -ne 0) { Fail "소스를 받지 못했어요. 인터넷을 확인하고 다시 실행하세요." }
    Set-Content -Path "$src\.picapp_version" -Value $Version -Encoding ASCII
} else {
    Say "  이미 받아 둔 소스를 써요."
}
if (-not (Test-Path "$src\laf\misc\skia-tag.txt")) { Fail "소스가 덜 받아졌어요. $src 폴더를 지우고 다시 실행하세요." }

# ---------------------------------------------------------------- 5. Skia
Step 5 "Skia (미리 빌드된 것) 받기"
$skiaTag = (Get-Content "$src\laf\misc\skia-tag.txt" -Raw).Trim()
$skia = "$Root\deps\skia-$skiaTag"
$skiaLib = "$skia\out\Release-x64"
if (-not (Test-Path "$skiaLib\skia.lib")) {
    $z = "$Root\deps\Skia-Windows-Release-x64.zip"
    Download "https://github.com/aseprite/skia/releases/download/$skiaTag/Skia-Windows-Release-x64.zip" $z
    Unzip $z $skia; Remove-Item $z
    if (-not (Test-Path "$skiaLib\skia.lib")) { Fail "Skia 압축을 풀었는데 skia.lib 가 없어요." }
}
Say "  Skia: $skia" "Green"

# ---------------------------------------------------------------- 6. 빌드 준비 (cmake)
Step 6 "빌드 설정 (cmake)"
# vcvars64.bat 이 만드는 환경 변수(컴파일러 경로 등)를 이 창으로 가져온다
$vcvars = Join-Path $vs "VC\Auxiliary\Build\vcvars64.bat"
cmd /c "`"$vcvars`" >nul 2>&1 && set" | ForEach-Object {
    if ($_ -match "^([^=]+)=(.*)$") { [Environment]::SetEnvironmentVariable($matches[1], $matches[2], "Process") }
}
if (-not (Get-Command cl.exe -ErrorAction SilentlyContinue)) { Fail "C++ 컴파일러(cl.exe)를 불러오지 못했어요." }
$env:Path = "$cmakeDir;$ninjaDir;" + $env:Path

$build = "$Root\build"
if ($Fresh -and (Test-Path $build)) { Say "  빌드 폴더를 지우고 처음부터 해요."; Remove-Item -Recurse -Force $build }
& "$cmakeDir\cmake.exe" -S $src -B $build -G Ninja `
    "-DCMAKE_BUILD_TYPE=RelWithDebInfo" `
    "-DCMAKE_C_COMPILER=cl" "-DCMAKE_CXX_COMPILER=cl" `
    "-DCMAKE_MAKE_PROGRAM=$ninjaDir\ninja.exe" `
    "-DLAF_BACKEND=skia" `
    "-DSKIA_DIR=$skia" "-DSKIA_LIBRARY_DIR=$skiaLib" "-DSKIA_LIBRARY=$skiaLib\skia.lib"
if ($LASTEXITCODE -ne 0) {
    Fail "빌드 설정에서 오류가 났어요. Aseprite_빌드.bat 을 다시 실행하고, 또 나면 '처음부터' 로 해 보세요 (안내서 참고)."
}

# ---------------------------------------------------------------- 7. 빌드 (ninja)
Step 7 "빌드 (처음에는 20~60분, 다시 할 때는 몇 분)"
$t0 = Get-Date
& "$cmakeDir\cmake.exe" --build $build --target aseprite
if ($LASTEXITCODE -ne 0) { Fail "빌드 중 오류가 났어요. 다시 실행하면 이어서 해요." }
$exe = "$build\bin\aseprite.exe"
if (-not (Test-Path $exe)) { Fail "빌드는 끝났는데 aseprite.exe 가 없어요." }
$min = [math]::Round(((Get-Date) - $t0).TotalMinutes)

# 바탕화면 바로가기 (한 번만)
try {
    $lnk = Join-Path ([Environment]::GetFolderPath("Desktop")) "Aseprite (내가 빌드).lnk"
    $sh = New-Object -ComObject WScript.Shell
    $s = $sh.CreateShortcut($lnk); $s.TargetPath = $exe; $s.WorkingDirectory = "$build\bin"; $s.Save()
    Say "  바탕화면에 바로가기를 만들었어요." "Green"
} catch {}

Say ""
Say "==============================================================" "Green"
Say " 다 됐어요! Aseprite $Version ($min 분)" "Green"
Say " 실행 파일: $exe" "Green"
Say " 그림 도구를 다시 켜면 결과 카드에 'Aseprite로 열기' 버튼이 생겨요." "Green"
Say " (이 exe 는 개인용이에요. 다른 사람에게 나눠 주면 안 돼요.)" "Green"
Say "==============================================================" "Green"
try { Stop-Transcript | Out-Null } catch {}
exit 0
