# Fixed query adapter. Only the application's validated SELECT compiler calls this.
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$connection = $null
try {
    $request = [Console]::In.ReadToEnd() | ConvertFrom-Json
    $settings = $request.connection
    $builder = New-Object System.Data.SqlClient.SqlConnectionStringBuilder
    $builder['Data Source'] = if ($settings.DB_PORT) { "$($settings.DB_HOST),$($settings.DB_PORT)" } else { $settings.DB_HOST }
    $builder['Initial Catalog'] = $settings.DB_NAME
    $builder['Connect Timeout'] = [int]$request.timeout
    $builder['Encrypt'] = ($settings.DB_SSL -ne 'false')
    $builder['TrustServerCertificate'] = $false
    $builder['ApplicationIntent'] = 'ReadOnly'
    if ($settings.DB_AUTH -eq 'windows') {
        $builder['Integrated Security'] = $true
    } else {
        $builder['User ID'] = $settings.DB_USER
        $builder['Password'] = $settings.DB_PASSWORD
    }
    $connection = New-Object System.Data.SqlClient.SqlConnection($builder.ConnectionString)
    $connection.Open()
    $command = $connection.CreateCommand()
    $command.CommandTimeout = [int]$request.timeout
    $command.CommandText = $request.sql
    $index = 0
    foreach ($item in $request.parameters) {
        $parameter = $command.CreateParameter()
        $parameter.ParameterName = "@p$index"
        switch ($item.type) {
            'number' { $parameter.SqlDbType = [System.Data.SqlDbType]::Decimal; $parameter.Value = [decimal]::Parse([string]$item.value, [Globalization.CultureInfo]::InvariantCulture) }
            'date' { $parameter.SqlDbType = [System.Data.SqlDbType]::Date; $parameter.Value = [datetime]::ParseExact([string]$item.value, 'yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture) }
            default { $parameter.SqlDbType = [System.Data.SqlDbType]::NVarChar; $parameter.Value = [string]$item.value }
        }
        [void]$command.Parameters.Add($parameter)
        $index++
    }
    $reader = $command.ExecuteReader()
    $rows = New-Object 'System.Collections.Generic.List[object]'
    while ($reader.Read()) {
        $row = [ordered]@{}
        for ($index = 0; $index -lt $reader.FieldCount; $index++) {
            $value = $reader.GetValue($index)
            if ($value -is [DBNull]) { $value = $null }
            elseif ($value -is [decimal]) { $value = $value.ToString([Globalization.CultureInfo]::InvariantCulture) }
            elseif ($value -is [datetime]) { $value = $value.ToString('yyyy-MM-dd') }
            $row[$reader.GetName($index)] = $value
        }
        $rows.Add($row)
    }
    $reader.Close()
    [Console]::Out.Write((ConvertTo-Json -InputObject @($rows.ToArray()) -Depth 8 -Compress))
} catch {
    [Console]::Error.Write('Database read failed.')
    exit 1
} finally {
    if ($connection) { $connection.Dispose() }
}
