param([Parameter(Mandatory=$true)][string]$ImageDirectory)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null=[Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime]
$null=[Windows.Storage.Streams.IRandomAccessStream,Windows.Storage.Streams,ContentType=WindowsRuntime]
$null=[Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics.Imaging,ContentType=WindowsRuntime]
$null=[Windows.Graphics.Imaging.SoftwareBitmap,Windows.Graphics.Imaging,ContentType=WindowsRuntime]
$null=[Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
$null=[Windows.Media.Ocr.OcrResult,Windows.Foundation,ContentType=WindowsRuntime]
function Await-WinRT($operation,[Type]$resultType) {
    $method=[System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {$_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'} | Select-Object -First 1
    $task=$method.MakeGenericMethod($resultType).Invoke($null,@($operation))
    $task.Wait()
    return $task.Result
}
$engine=[Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if(-not $engine){throw 'Windows OCR language pack unavailable'}
foreach($image in Get-ChildItem -LiteralPath $ImageDirectory -Filter '*.png' | Sort-Object Name){
    $out=[IO.Path]::ChangeExtension($image.FullName,'.txt')
    if(Test-Path -LiteralPath $out){continue}
    $file=Await-WinRT ([Windows.Storage.StorageFile]::GetFileFromPathAsync($image.FullName)) ([Windows.Storage.StorageFile])
    $stream=Await-WinRT ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    try{
        $decoder=Await-WinRT ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $bitmap=Await-WinRT ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        $result=Await-WinRT ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
        $lines=($result.Lines | ForEach-Object {$_.Text}) -join "`n"
        [IO.File]::WriteAllText($out,$lines,[Text.UTF8Encoding]::new($false))
        $bitmap.Dispose()
    }finally{$stream.Dispose()}
}
Write-Output 'Windows OCR complete'
