[CmdletBinding()]
param(
    [switch]$Preview
)

$CommandArguments = @(
    "run",
    "python",
    ".\tools\organize_toeic_files.py"
)

if ($Preview) {
    $CommandArguments += "--preview"
}

& uv @CommandArguments
exit $LASTEXITCODE
