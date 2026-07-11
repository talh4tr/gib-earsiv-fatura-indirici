<?php
/**
 * GİB Portal Arşiv Helper Entegrasyonu
 * Developed by: talh4tr (https://github.com/talh4tr)
 * License: MIT
 */
require 'vendor/autoload.php';

// Tüm PHP hata raporlamasını kapat, ekrana (stdout'a) hiçbir uyarı/notice sızmasın.
// Bunlar JSON çıktısını bozar.
error_reporting(0);
ini_set('display_errors', '0');

function maskSensitiveData(string $message, string $password = ''): string
{
    if (!empty($password) && strlen($password) >= 3) {
        // Şifre metni mesaj içinde geçiyorsa maskele
        $message = str_replace($password, '***MASKELENDI***', $message);
    }
    // Yaygın kimlik bilgisi anahtar kelimelerini içeren olası key=value kalıplarını da maskele
    $message = preg_replace('/(sifre|password|parola|sifre2)["\']?\s*[:=]\s*["\']?[^"\'\s,}]+/i', '$1=***MASKELENDI***', $message);
    return $message;
}

/**
 * Verilen başlangıç-bitiş tarih aralığını (DD/MM/YYYY formatında), GİB'in
 * sessiz kırpma riskine karşı en fazla 7 günlük alt aralıklara böler.
 * Dönüş: [['baslangic' => 'DD/MM/YYYY', 'bitis' => 'DD/MM/YYYY'], ...]
 */
function splitDateRangeWeekly(string $startDate, string $endDate): array
{
    $chunks = [];
    $start = \DateTime::createFromFormat('d/m/Y', $startDate);
    $end = \DateTime::createFromFormat('d/m/Y', $endDate);

    if (!$start || !$end || $start > $end) {
        // Geçersiz veya ters aralık — tek parça olarak orijinal haliyle dön,
        // mevcut validasyon (FormatValidator) zaten bunu ayrıca kontrol ediyor.
        return [['baslangic' => $startDate, 'bitis' => $endDate]];
    }

    $current = clone $start;
    while ($current <= $end) {
        $chunkEnd = (clone $current)->modify('+6 days'); // 7 günlük pencere (bugün dahil)
        if ($chunkEnd > $end) {
            $chunkEnd = clone $end;
        }
        $chunks[] = [
            'baslangic' => $current->format('d/m/Y'),
            'bitis' => $chunkEnd->format('d/m/Y'),
        ];
        $current = (clone $chunkEnd)->modify('+1 day');
    }

    return $chunks;
}

function dedupInvoicesByUuid(array $invoices): array
{
    $seen = [];
    $result = [];
    foreach ($invoices as $invoice) {
        $uuid = $invoice['ettn'] ?? null;
        if ($uuid === null) {
            // uuid'si olmayanı olduğu gibi bırak, zaten $downloadFunc bunu
            // ayrıca "failed" olarak işaretleyecek (K4 patch'i).
            $result[] = $invoice;
            continue;
        }
        if (!isset($seen[$uuid])) {
            $seen[$uuid] = true;
            $result[] = $invoice;
        }
    }
    return $result;
}

function checkSuspiciousLimit(int $count, string $rangeLabel): ?string
{
    $knownThresholds = [500, 250, 100];
    foreach ($knownThresholds as $threshold) {
        // Tam eşitse veya eşiğin %98'i ve üzerindeyse şüpheli say
        if ($count === $threshold || ($count >= $threshold * 0.98 && $count < $threshold)) {
            return "UYARI: '{$rangeLabel}' aralığında dönen kayıt sayısı ({$count}) GİB'in bilinen bir limit eşiğine ({$threshold}) çok yakın veya eşit. Bu aralıkta veri kırpılmış (eksik gelmiş) olabilir.";
        }
    }
    return null;
}

function resolveSelectedFilterTypes(string|array $filterType): array
{
    if (is_array($filterType)) {
        $requested = $filterType;
    } else {
        $requested = match ($filterType) {
            'signed' => ['signed'],
            'deleted' => ['deleted'],
            'objected' => ['objected'],
            'both' => ['signed', 'deleted'],
            'all' => ['signed', 'deleted', 'objected'],
            default => preg_split('/[,|]/', $filterType) ?: [],
        };
    }

    $allowed = ['signed', 'deleted', 'objected'];
    $selected = [];
    foreach ($requested as $type) {
        $type = trim((string)$type);
        if (in_array($type, $allowed, true) && !in_array($type, $selected, true)) {
            $selected[] = $type;
        }
    }

    return $selected;
}

// Global exception/error handler — try-catch'in yakalayamadığı fatal error'ları
// (Throwable ama Exception olmayanlar dahil) burada yakala.
set_exception_handler(function ($e) {
    global $password;
    $pass = isset($password) ? $password : '';
    $msg = maskSensitiveData($e->getMessage(), $pass);
    echo json_encode([
        'error' => 'GIB_HATA: ' . $msg,
        'error_type' => get_class($e)
    ]);
    exit(1);
});

// PHP fatal error'ları (parse error, memory limit, vs.) shutdown sırasında yakala.
register_shutdown_function(function () {
    $error = error_get_last();
    if ($error !== null && in_array($error['type'], [E_ERROR, E_PARSE, E_CORE_ERROR, E_COMPILE_ERROR])) {
        global $password;
        $pass = isset($password) ? $password : '';
        $msg = maskSensitiveData($error['message'], $pass);
        echo json_encode([
            'error' => 'GIB_KRITIK_HATA: ' . $msg,
            'error_type' => 'FatalError'
        ]);
    }
});

use Mlevent\Fatura\Gib;

class CustomGib extends Gib
{
    /**
     * Custom saveToDisk method supporting custom onayDurumu status
     */
    public function saveToDiskCustom(string $uuid, ?string $dirName = null, ?string $fileName = null, string $onayDurumu = 'Onaylandı'): string|bool
    {
        $saveDir = realpath($dirName ?? '.' . DIRECTORY_SEPARATOR);
        $fullDir = join(DIRECTORY_SEPARATOR, [$saveDir, $fileName ?? $uuid]) . '.zip';
        $options = [
            'http' => [
                'user_agent' => 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36',
                'ignore_errors' => true
            ]
        ];

        if (!$saveDir) {
            throw new \InvalidArgumentException("Geçersiz dosya yolu: {$dirName}");
        }

        // Define status candidates to attempt downloading the invoice
        $candidates = [$onayDurumu];
        if ($onayDurumu === 'Silinmiş') {
            $candidates[] = 'Onaylandı';
            $candidates[] = 'İptal';
            $candidates[] = 'İptal Edildi';
            $candidates[] = 'Silinmis';
        } elseif (str_contains(strtolower($onayDurumu), 'itiraz') || str_contains($onayDurumu, 'İtiraz')) {
            $candidates[] = 'Onaylandı';
            $candidates[] = 'İtiraz Edildi';
            $candidates[] = 'İtiraz';
            $candidates[] = 'Onaylanmadı';
        } else {
            $candidates[] = 'Onaylanmadı';
        }
        $candidates = array_unique($candidates);

        $rawResponse = false;
        $successfulStatus = null;
        $errors = [];

        foreach ($candidates as $candidate) {
            $downloadUrl = $this->getGateway('download') . '?' . http_build_query([
                'token'      => $this->token,
                'ettn'       => $this->setUuid($uuid),
                'onayDurumu' => $candidate,
                'belgeTip'   => $this->documentType->value,
                'cmd'        => 'EARSIV_PORTAL_BELGE_INDIR'
            ]);

            $response = @file_get_contents($downloadUrl, false, stream_context_create($options));
            $statusLine = isset($http_response_header[0]) ? $http_response_header[0] : 'HTTP/1.1 500 Unknown';

            // If response starts with ZIP magic signature bytes, it is a valid zip archive
            if (is_string($response) && substr($response, 0, 4) === "PK\x03\x04") {
                $rawResponse = $response;
                $successfulStatus = $candidate;
                break;
            } else {
                $truncatedResponse = is_string($response) ? substr($response, 0, 300) : 'FALSE';
                error_log("[GIB Arşiv Debug] Try status '{$candidate}' failed for UUID {$uuid}. HTTP Status: {$statusLine}. Body: {$truncatedResponse}");
                
                $errors[$candidate] = [
                    'status' => $statusLine,
                    'length' => is_string($response) ? strlen($response) : 'FALSE',
                    'body'   => $truncatedResponse
                ];
            }
        }

        // Write permanent logs to logs/gib_debug.log
        $debugLogFile = __DIR__ . '/logs/gib_debug.log';
        $debugMsg = "[" . date('Y-m-d H:i:s') . "] UUID: " . $uuid . "\n";
        if ($successfulStatus !== null) {
            $debugMsg .= "[" . date('Y-m-d H:i:s') . "] SUCCESS: Downloaded ZIP using status: '" . $successfulStatus . "'\n";
        } else {
            $debugMsg .= "[" . date('Y-m-d H:i:s') . "] FAILURE: Could not download ZIP. Attempts:\n";
            foreach ($errors as $status => $info) {
                $debugMsg .= "  - Status attempted: '" . $status . "' | HTTP Status: " . $info['status'] . " | Length: " . $info['length'] . "\n";
                if (!empty($info['body'])) {
                    $debugMsg .= "    Body snippet: " . $info['body'] . "\n";
                }
            }
        }
        $debugMsg .= "--------------------------------------------------\n";
        @file_put_contents($debugLogFile, $debugMsg, FILE_APPEND);

        if ($rawResponse !== false && file_put_contents($fullDir, $rawResponse)) {
            return $fullDir;
        }
        return false;
    }

    public function onlyObjected(): self
    {
        $this->setFilters(['onayDurumu' => 'İtiraz']);
        return $this;
    }
}

// Read JSON input from stdin
$input = file_get_contents('php://stdin');
$params = json_decode($input, true);

if (!$params) {
    echo json_encode(['error' => 'Geçersiz parametre girdisi (JSON çözülemedi).']);
    exit(1);
}

$username = $params['username'] ?? '';
$password = $params['password'] ?? '';
$startDate = $params['startDate'] ?? '';
$endDate = $params['endDate'] ?? '';
$testMode = (bool)($params['testMode'] ?? false);
$filterTypes = $params['filterTypes'] ?? null;
$filterType = $params['filterType'] ?? 'both'; // signed, deleted, objected, both, all or comma-separated values
$direction = $params['direction'] ?? 'outgoing'; // outgoing, incoming
$outputDir = $params['outputDir'] ?? '';

if (empty($startDate) || empty($endDate) || empty($outputDir)) {
    echo json_encode(['error' => 'Eksik tarih veya çıkış dizini girdisi.']);
    exit(1);
}

if (!$testMode && (empty($username) || empty($password))) {
    echo json_encode(['error' => 'Giriş bilgileri eksik.']);
    exit(1);
}

try {
    $gib = new CustomGib();
    if ($testMode) {
        if (empty($username)) {
            $gib->setTestCredentials()->login();
        } else {
            $gib->setTestCredentials($username, $password)->login();
        }
    } else {
        $gib->setCredentials($username, $password)->login();
    }

    $downloaded = [];
    $failed = [];
    $totalFound = 0;

    // Helper to process download
    $downloadFunc = function($gib, $invoices, $type, $outputDir, &$downloaded, &$failed) use ($password) {
        foreach ($invoices as $invoice) {
            $uuid = $invoice['ettn'] ?? null;
            $num = $invoice['belgeNumarasi'] ?? null;
            $date = $invoice['belgeTarihi'] ?? null;
            
            if (!$uuid) {
                $failed[] = [
                    'belgeNumarasi' => $num,
                    'uuid' => 'BILINMIYOR',
                    'message' => 'GİB portalından ETTN (UUID) bilgisi olmadan dönen fatura kaydı — işlenemedi.'
                ];
                continue;
            }
            
            try {
                // Determine the correct onayDurumu based on the invoice type (signed/deleted/objected)
                $onayDurumu = ($type === 'deleted') ? 'Silinmiş' : (($type === 'objected') ? 'İtiraz Edildi' : 'Onaylandı');
                // Save ZIP file using ETTN (UUID) as filename
                $zipPath = $gib->saveToDiskCustom($uuid, $outputDir, $uuid, $onayDurumu);
                if ($zipPath) {
                    $downloaded[] = [
                        'uuid' => $uuid,
                        'belgeNumarasi' => $num,
                        'belgeTarihi' => $date,
                        'type' => $type, // 'signed', 'deleted', or 'objected'
                        'zipPath' => $zipPath
                    ];
                } else {
                    $failed[] = [
                        'belgeNumarasi' => $num,
                        'uuid' => $uuid,
                        'message' => 'Fatura diske kaydedilemedi (saveToDisk() boş/geçersiz sonuç döndü).'
                    ];
                }
            } catch (\Throwable $e) {
                // Append failed invoice details
                $safeMessage = maskSensitiveData($e->getMessage(), $password);
                $failed[] = [
                    'belgeNumarasi' => $num,
                    'uuid' => $uuid,
                    'message' => 'GIB_HATA: ' . $safeMessage
                ];
                continue;
            }
        }
    };

    $dateChunks = splitDateRangeWeekly($startDate, $endDate);
    $suspiciousWarnings = [];

    $queryAndDownload = function(string $type) use ($gib, $dateChunks, $downloadFunc, $outputDir, &$downloaded, &$failed, &$suspiciousWarnings): int {
        $invoices = [];
        $labelByType = [
            'signed' => 'Imzali',
            'deleted' => 'Iptal',
            'objected' => 'Itiraz',
        ];

        foreach ($dateChunks as $chunk) {
            $rangeLabel = "{$chunk['baslangic']} - {$chunk['bitis']} ({$labelByType[$type]})";
            if ($type === 'signed') {
                $gib->onlySigned();
            } elseif ($type === 'deleted') {
                $gib->onlyDeleted();
            } elseif ($type === 'objected') {
                $gib->onlyObjected();
            }

            $chunkInvoices = $gib->getAll($chunk['baslangic'], $chunk['bitis']);

            $warning = checkSuspiciousLimit(count($chunkInvoices), $rangeLabel);
            if ($warning !== null) {
                $suspiciousWarnings[] = $warning;
            }

            $invoices = array_merge($invoices, $chunkInvoices);
        }

        $invoices = dedupInvoicesByUuid($invoices);
        $downloadFunc($gib, $invoices, $type, $outputDir, $downloaded, $failed);

        return count($invoices);
    };

    if ($direction === 'incoming') {
        $invoices = [];
        foreach ($dateChunks as $chunk) {
            $rangeLabel = "{$chunk['baslangic']} - {$chunk['bitis']}";
            $chunkInvoices = $gib->getAllIssuedToMe($chunk['baslangic'], $chunk['bitis']);

            $warning = checkSuspiciousLimit(count($chunkInvoices), $rangeLabel);
            if ($warning !== null) {
                $suspiciousWarnings[] = $warning;
            }

            $invoices = array_merge($invoices, $chunkInvoices);
        }
        $invoices = dedupInvoicesByUuid($invoices);
        $totalFound = count($invoices);
        $downloadFunc($gib, $invoices, 'signed', $outputDir, $downloaded, $failed);
    } else {
        $selectedFilterTypes = resolveSelectedFilterTypes($filterTypes !== null ? $filterTypes : $filterType);
        if (empty($selectedFilterTypes)) {
            echo json_encode(['error' => 'Geçersiz fatura tipi seçimi.']);
            exit(1);
        }

        foreach ($selectedFilterTypes as $selectedType) {
            $totalFound += $queryAndDownload($selectedType);
        }
    }

    echo json_encode([
        'success' => true,
        'downloaded' => $downloaded,
        'failed' => $failed,
        'totalFound' => $totalFound,
        'suspiciousWarnings' => $suspiciousWarnings
    ]);

} catch (\Throwable $e) {
    $msg = maskSensitiveData($e->getMessage(), $password);

    // GİB'e özgü bilinen hata durumları için daha spesifik mesajlar
    if (stripos($msg, 'timeout') !== false || stripos($msg, 'timed out') !== false) {
        $errorMsg = 'GIB_TIMEOUT: GİB portalı yanıt vermedi (zaman aşımı).';
    } elseif (stripos($msg, '401') !== false || stripos($msg, 'unauthorized') !== false || stripos($msg, 'kimlik') !== false) {
        $errorMsg = 'GIB_YETKI_HATASI: Kullanıcı adı veya şifre hatalı.';
    } else {
        $errorMsg = 'GIB_HATA: ' . $msg;
    }

    echo json_encode([
        'error' => $errorMsg,
        'error_type' => get_class($e)
    ]);
    exit(1);
}
