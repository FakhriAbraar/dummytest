<?php

error_reporting(E_ALL);
ini_set("display_errors", 1);

header("Access-Control-Allow-Origin: http://localhost:5173");
header("Access-Control-Allow-Methods: POST, OPTIONS");
header("Access-Control-Allow-Headers: Content-Type");
header("Content-Type: application/json");

if ($_SERVER["REQUEST_METHOD"] === "OPTIONS") {
    http_response_code(200);
    exit();
}

/* =====================================================
   INPUT
===================================================== */

$task = $_POST["task"] ?? "TEXT_CLASSIFICATION";
$content = trim($_POST["content"] ?? "");

if (
    empty($content)
    && !isset($_FILES["image"])
) {
    echo json_encode([
        "error" => "Content kosong"
    ]);
    exit();
}


/* =====================================================
   BUILD USER CONTENT
===================================================== */

if ($task === "IMG_CLASSIFICATION") {

    $userContent = [];

    if (!empty($content)) {

        $userContent[] = [
            "type" => "text",
            "text" => $content
        ];
    }

    if (isset($_FILES["image"])) {

        $imageData = base64_encode(
            file_get_contents(
                $_FILES["image"]["tmp_name"]
            )
        );

        $mimeType =
            $_FILES["image"]["type"];

        $userContent[] = [
            "type" => "image_url",
            "image_url" => [
                "url" =>
                    "data:$mimeType;base64,$imageData"
            ]
        ];
    }

} else {
    // TEXT_CLASSIFICATION
    // KEYWORD_EXTRACTION
    $userContent = $content;
}

/*==========================================
   SYSTEM PROMPT
===================================================== */

switch ($task) {
    case "KEYWORD_EXTRACTION":
        $systemPrompt =
            "[TASK: KEYWORD_EXTRACTION]\nEkstraksi semua kata kunci penting dari teks berikut dengan cara mengambil langsung dari teks asli, jangan ubah atau tambahkan apapun. Format hasilnya sebagai JSON array of strings";

        break;

    case "IMG_CLASSIFICATION":
        $systemPrompt =
            "[TASK: IMG_CLASSIFICATION]\nTugas: Analisis gambar atau teks yang diberikan, lalu tentukan klasifikasi rating usia dan deskripsi analisisnya berdasarkan karakteristik data berikut.\n\nAturan Klasifikasi Rating:\n* \"Semua Umur\" -> Data netral, aman, bersifat edukatif, atau ramah anak tanpa adanya unsur ketegangan, ancaman, maupun darah.\n* \"7+\" -> Konten fantasi/animasi ringan, prosedur medis klinis luar tubuh yang damai, atau objek senjata yang terdistorsi dalam bentuk mainan anak plastik/neon.\n* \"13+\" -> Aktivitas simulasi taktis militer, replika senjata gelap/kamuflase (Airsoft), olahraga kontak fisik intens, atau romansa pasangan ringan tanpa cedera fatal atau darah fotorealistis.\n* \"15+\" -> Realitas keras dewasa, mencakup tindakan medis invasif/bedah organ, konflik fisik nyata (perkelahian/pengeroyokan), atau keberadaan fisik senjata api/tajam asli dalam posisi diam.\n* \"18+\" -> Konten khusus dewasa yang memuat penggunaan zat adiktif (rokok/alkohol), perilaku membahayakan diri sendiri (self-harm), atau sensualitas tingkat tinggi dengan pakaian minim tanpa ketelanjangan vulgar.\n* \"Konten Terlarang\" -> Pelanggaran hukum atau norma mutlak seperti pornografi/ketelanjangan alat vital, aktivitas terorisme/propaganda radikal, ancaman senjata mematikan secara langsung, atau penggunaan aktif narkoba keras.\n\nAturan Penanganan Ambiguitas (Anti-Halusinasi):\n- Lakukan analisis objek secara objektif dan mendalam terlebih dahulu sebelum menentukan rating. Jangan malas menebak jika objek di dalam gambar terlihat jelas.\n- Namun, jika gambar sangat kabur (blur), tidak memiliki konteks objek yang jelas, atau Anda benar-benar tidak yakin demi menghindari halusinasi prediksi yang fatal, gunakan rating \"Unrated\".\n\nAturan Output:\n- Wajib merespons hanya dalam format JSON valid tanpa teks tambahan di luar JSON.\n- Jangan gunakan markdown block (jangan gunakan ```json).\n\nFormat Output:\n{\n\"rating\": \"...\",\n\"description\": \"...\"\n}";

        break;

    default:
        $systemPrompt =
            "[TASK: TEXT_CLASSIFICATION]\nAnda adalah sistem moderasi konten media sosial Indonesia. Tugas Anda adalah mengklasifikasikan caption/teks media sosial ke dalam kategori rating usia yang tepat dan berikan penjelasannya.\n\nDEFINISI RATING:\n- Semua Umur (Semua Umur): Konten positif, aman, dan ramah keluarga. Tidak ada unsur negatif apapun.\n- 7+: Hiburan dan fiksi ringan untuk anak SD. Boleh ada persaingan atau tantangan ringan, TANPA kekerasan realistis atau bahasa kasar.\n- 13+: Konten remaja awal. Boleh ada konflik sosial, curahan hati, misteri fiksi. TANPA unsur dewasa atau kekerasan grafis.\n- 15+: Konten remaja akhir. Boleh ada diskusi politik ringan, isu sosial, berita faktual, kriminalitas tanpa glorifikasi.\n- 18+: Konten dewasa yang LEGAL. Mencakup: alkohol, rokok, romansa dewasa (tanpa eksplisit), kehidupan malam.\n- Konten Terlarang (Konten Terlarang): HANYA untuk konten yang secara EKSPLISIT mengandung: (1) ancaman kekerasan fisik langsung, (2) pelecehan/objektifikasi seksual, (3) promosi judi online dengan kata kunci slot/gacor/scatter, (4) ujaran kebencian SARA secara langsung.\n\nFORMAT OUTPUT:\nRating: [Semua Umur / 7+ / 13+ / 15+ / 18+ / Konten Terlarang]\nPenjelasan: [Penjelasan Logis 2-4 kalimat, sebutkan frasa spesifik sebagai penguat penjelasan jika ada atau memungkinkan]. Output wajib JSON valid:
            {
            \"rating\":\"...\",
            \"description\":\"...\"
            }

            Jangan keluarkan teks selain JSON.";
}

/* =====================================================
   REQUEST PAYLOAD
===================================================== */
$data = [
    "model" => "itspad",

    "messages" => [

        [
            "role" => "system",
            "content" => $systemPrompt
        ],

        [
            "role" => "user",
            "content" => $userContent
        ]
    ],

    "temperature" => 0,
    "max_tokens" => 512
];

/* =====================================================
   CALL VLLM
===================================================== */

$ch = curl_init();

curl_setopt(
    $ch,
    CURLOPT_URL,
    "https://5t4gp3ab7iv7cr-8001.proxy.runpod.net/v1/chat/completions"
);

curl_setopt(
    $ch,
    CURLOPT_RETURNTRANSFER,
    true
);

curl_setopt(
    $ch,
    CURLOPT_POST,
    true
);

curl_setopt(
    $ch,
    CURLOPT_HTTPHEADER,
    [
        "Content-Type: application/json"
    ]
);

curl_setopt(
    $ch,
    CURLOPT_POSTFIELDS,
    json_encode($data)
);

$response = curl_exec($ch);

$result = json_decode(
    $response,
    true
);

if (curl_errno($ch)) {
    echo json_encode([
        "error" => curl_error($ch)
    ]);
    curl_close($ch);
    exit();
}

curl_close($ch);

/* =====================================================
   RESPONSE VALIDATION
===================================================== */

$result = json_decode(
    $response,
    true
);

if (
    !isset(
        $result["choices"][0]["message"]["content"]
    )
) {

    echo json_encode([
        "error" => "Invalid VLLM Response",
        "raw_response" => $response
    ]);

    exit();
}

$output =
    trim(
        $result["choices"][0]["message"]["content"]
    );

/* =====================================================
   KEYWORD EXTRACTION
===================================================== */
if (
    $task === "KEYWORD_EXTRACTION"
) {

    echo json_encode([
        "task" =>
            "KEYWORD_EXTRACTION",

        "rating" =>
            "KEYWORD",

        "description" =>
            $output,

        "raw_output" =>
            $output

    ]);

    exit();
}

/* =====================================================
   PARSE OUTPUT
===================================================== */
$rating = "UNKNOWN";
$description = "";

$cleanOutput = trim($output);

/* ---------------------------------------------
   HAPUS MARKDOWN
---------------------------------------------- */
$cleanOutput = preg_replace(
    '/^```json\s*/i',
    '',
    $cleanOutput
);

$cleanOutput = preg_replace(
    '/^```\s*/',
    '',
    $cleanOutput
);

$cleanOutput = preg_replace(
    '/```\s*$/',
    '',
    $cleanOutput
);

/* ---------------------------------------------
   JSON LANGSUNG
---------------------------------------------- */

$obj = json_decode(
    $cleanOutput,
    true
);

if (
    json_last_error() === JSON_ERROR_NONE
    && is_array($obj)
) {

    $rating = trim(
        $obj["rating"]
        ??
        $obj["Rating"]
        ??
        "UNKNOWN"
    );

    $description = trim(
        $obj["description"]
        ??
        $obj["Description"]
        ??
        ""
    );
}

/* ---------------------------------------------
   JSON EMBEDDED
---------------------------------------------- */
if (
    $rating === "UNKNOWN"
    &&
    preg_match(
        '/\{.*\}/s',
        $cleanOutput,
        $matches
    )
) {

    $obj = json_decode(
        $matches[0],
        true
    );

    if (
        json_last_error() === JSON_ERROR_NONE
        && is_array($obj)
    ) {

        $rating = trim(
            $obj["rating"]
            ??
            $obj["Rating"]
            ??
            "UNKNOWN"
        );

        $description = trim(
            $obj["description"]
            ??
            $obj["Description"]
            ??
            ""
        );
    }
}

$validRatings = [
    "Semua Umur",
    "7+",
    "13+",
    "15+",
    "18+",
    "Konten Terlarang",
    "Unrated"
];

if ($rating === "UNKNOWN") {
    foreach ($validRatings as $r) {
        if (
            stripos(
                $cleanOutput,
                $r
            ) !== false
        ) {

            $rating = $r;
            break;
        }
    }
}

/* ---------------------------------------------
   FORMAT:
   Rating:
   Penjelasan:
---------------------------------------------- */

if ($rating === "UNKNOWN") {
    if (
        preg_match(
            '/Rating\s*:\s*(.+)/i',
            $cleanOutput,
            $m
        )
    ) {
        $rating = trim(
            explode(
                "\n",
                $m[1]
            )[0]
        );
    }

    if (
        preg_match(
            '/Penjelasan\s*:\s*(.*)/is',
            $cleanOutput,
            $m
        )
    ) {

        $description =
            trim($m[1]);
    }
}

/* ---------------------------------------------
   FALLBACK
---------------------------------------------- */
if (
    empty($description)
) {

    $description =
        $cleanOutput;
}

/* =====================================================
   RESPONSE
===================================================== */
echo json_encode([
    "debug" => [
        "model" => $data["model"],
        "system_prompt" => substr(
            $systemPrompt,
            0,
            300
        )
    ],
    "task" => $task,
    "rating" => $rating,
    "description" => $description,
    "raw_output" => $output
]);
