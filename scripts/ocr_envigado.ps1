param([string]$Directorio = "data/raw/ocr_envigado")

# Ejecutar con Windows PowerShell 5.1 y el componente de OCR en español.
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Media.Ocr, ContentType=WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType=WindowsRuntime]
$convertir = [System.WindowsRuntimeSystemExtensions].GetMethods() |
    Where-Object { $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 } |
    Select-Object -First 1

function Esperar($Operacion, [type]$Tipo) {
    $tarea = $convertir.MakeGenericMethod($Tipo).Invoke($null, @($Operacion))
    $tarea.GetAwaiter().GetResult()
}

$idioma = [Windows.Globalization.Language]::new('es-ES')
$ocr = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($idioma)
if (!$ocr) { throw 'Falta el reconocimiento de texto de Windows en español (España).' }

foreach ($imagen in Get-ChildItem -LiteralPath $Directorio -Filter '*.png') {
    $archivo = Esperar ([Windows.Storage.StorageFile]::GetFileFromPathAsync($imagen.FullName)) ([Windows.Storage.StorageFile])
    $stream = Esperar ($archivo.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    try {
        $decoder = Esperar ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $bitmap = Esperar ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        try {
            $resultado = Esperar ($ocr.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
            $lineas = foreach ($linea in $resultado.Lines) {
                foreach ($palabra in $linea.Words) {
                    [pscustomobject]@{
                        texto = $palabra.Text
                        x = [int]$palabra.BoundingRect.X
                        y = [int]$palabra.BoundingRect.Y
                    }
                }
            }
            $ruta = [IO.Path]::ChangeExtension($imagen.FullName, '.json')
            [IO.File]::WriteAllText($ruta, (ConvertTo-Json -InputObject @($lineas) -Compress))
        } finally {
            $bitmap.Dispose()
        }
    } finally {
        $stream.Dispose()
    }
}
