/* shared.js — 접수/의사 모니터 공유 로직 (DB 연동) */
(function (global) {

  const BASE_DISEASES_15 = [
    "고혈압", "당뇨병", "만성신장병(CKD)", "간질환", "소화성궤양",
    "심부전", "전립선비대", "녹내장", "천식·COPD", "뇌졸중",
    "고지혈증", "갑상선질환", "치매", "파킨슨병", "간질(경련)"
  ];

  /* ===== 질환명 → DB 필드 매핑 ===== */
  const DISEASE_DB_MAP = {
    "고혈압":          ["hypertension"],
    "당뇨병":          ["diabetes_type2"],
    "만성신장병(CKD)": ["ckd"],
    "간질환":          ["liver_disease"],
    "심부전":          ["heart_failure"],
    "뇌졸중":          ["stroke"],
    "고지혈증":        ["hyperlipidemia"],
    "갑상선질환":      ["thyroid_disease"],
    "천식·COPD":       ["asthma", "copd"],
  };
  /* DB 스키마에 없는 질환 → clinical_notes.extra_diseases */
  const EXTRA_DISEASE_NAMES = ["소화성궤양", "전립선비대", "녹내장", "치매", "파킨슨병", "간질(경련)"];

  /* ===== 인메모리 캐시 + 폴링 ===== */
  let _cache = [];
  let _pollTimer = null;

  function _getExtraDiseases(baseDiseases) {
    return (baseDiseases || []).filter(d => EXTRA_DISEASE_NAMES.includes(d));
  }

  function _buildDiseases(baseDiseases) {
    const flags = {};
    (baseDiseases || []).forEach(d => {
      const fields = DISEASE_DB_MAP[d];
      if (fields) fields.forEach(f => { flags[f] = true; });
    });
    return flags;
  }

  function _buildLabValues(labs) {
    const v = {};
    if (labs?.eGFR != null) v.egfr = labs.eGFR;
    if (labs?.K    != null) v.potassium = labs.K;
    if (labs?.Na   != null) v.sodium = labs.Na;
    return v;
  }

  function _buildClinicalNotes(p, queue_status) {
    return JSON.stringify({
      name:          p.name,
      chartNo:       p.chartNo,
      customBases:   p.customBases || [],
      lifestyle: {
        pregnant:     !!p.pregnant,
        breastfeeding: !!p.breastfeeding,
        smoker:        !!p.smoker,
        alcohol:       !!p.alcohol,
      },
      extra_diseases: _getExtraDiseases(p.baseDiseases || []),
      labs_extra: {
        qtc_ms:    p.labs?.QTc    || null,
        bp_raw:    p.labs?.BP     || "",
        astalt_raw: p.labs?.ASTALT || "",
      },
      lab_notes:      p.labNotes || "",
      physician_note: p.note || "",
      queue_status:   queue_status || "waiting",
      created_at_ts:  p.createdAt,
    });
  }

  function _toCreatePayload(p) {
    return {
      patient_code: p.id,
      age:          p.age || 0,
      gender:       p.gender || "M",
      weight_kg:    p.weight || null,
      height_cm:    p.height || null,
      diseases:     _buildDiseases(p.baseDiseases),
      lab_values:   _buildLabValues(p.labs),
      allergies:    p.allergies || [],
      current_medications: {
        history:      p.history      || "",
        prescription: p.prescription || "",
      },
      clinical_notes: _buildClinicalNotes(p, "waiting"),
    };
  }

  function _fromApiPatient(ap) {
    let notes = {};
    try { notes = JSON.parse(ap.clinical_notes || "{}"); } catch {}
    const meds   = ap.current_medications || {};
    const labs   = ap.lab_values || {};

    /* 역매핑: DB diseases → 한글 baseDiseases */
    const diseases = ap.diseases || {};
    const baseDiseases = [];
    Object.entries(DISEASE_DB_MAP).forEach(([korName, fields]) => {
      if (fields.every(f => diseases[f])) baseDiseases.push(korName);
    });
    const extraDiseases = notes.extra_diseases || [];

    return {
      id:           ap.patient_code,
      _dbId:        ap.id,
      createdAt:    notes.created_at_ts || 0,
      name:         notes.name    || ap.patient_code,
      chartNo:      notes.chartNo || "-",
      gender:       ap.gender,
      age:          ap.age,
      weight:       ap.weight_kg,
      height:       ap.height_cm,
      pregnant:     !!(notes.lifestyle?.pregnant),
      breastfeeding: !!(notes.lifestyle?.breastfeeding),
      smoker:       !!(notes.lifestyle?.smoker),
      alcohol:      !!(notes.lifestyle?.alcohol),
      baseDiseases: [...baseDiseases, ...extraDiseases],
      customBases:  notes.customBases || [],
      allergies:    ap.allergies || [],
      history:      meds.history      || "",
      labs: {
        eGFR:   labs.egfr      ?? null,
        ASTALT: notes.labs_extra?.astalt_raw || "",
        K:      labs.potassium ?? null,
        Na:     labs.sodium    ?? null,
        QTc:    notes.labs_extra?.qtc_ms || null,
        BP:     notes.labs_extra?.bp_raw || "",
      },
      labNotes:     notes.lab_notes || "",
      note:         notes.physician_note || "",
      prescription: meds.prescription || "",
    };
  }

  async function _createPatient(p) {
    try {
      const res = await fetch("/api/v1/patients/", {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify(_toCreatePayload(p)),
      });
      if (res.ok) {
        const created = await res.json();
        p._dbId = created.id;
      }
    } catch (e) {
      console.warn("[RxAssist] create failed:", e);
    }
  }

  async function _patchPatient(dbId, payload) {
    try {
      await fetch("/api/v1/patients/" + dbId, {
        method:  "PATCH",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify(payload),
      });
    } catch (e) {
      console.warn("[RxAssist] patch failed:", e);
    }
  }

  async function _markDone(p) {
    if (!p._dbId) return;
    await _patchPatient(p._dbId, {
      clinical_notes: _buildClinicalNotes(p, "done"),
    });
  }

  function _queueFingerprint(q) {
    // id + 주요 필드만으로 변경 감지 — 동일하면 이벤트 미발송
    return q.map(p => `${p.id}|${p._dbId || ""}|${p.prescription || ""}|${p.note || ""}|${p.name}|${p.age}`).join("§");
  }
  let _lastFp = "";

  async function _fetchQueue() {
    try {
      const res = await fetch("/api/v1/patients/?limit=200");
      if (!res.ok) return;
      const data = await res.json();
      const waiting = data
        .filter(ap => {
          let notes = {};
          try { notes = JSON.parse(ap.clinical_notes || "{}"); } catch {}
          return notes.queue_status !== "done";
        })
        .map(_fromApiPatient)
        .sort((a, b) => a.createdAt - b.createdAt);
      const fp = _queueFingerprint(waiting);
      _cache = waiting;
      if (fp !== _lastFp) {
        _lastFp = fp;
        window.dispatchEvent(new CustomEvent("rxassist:update"));
      }
    } catch (e) {
      console.warn("[RxAssist] poll failed:", e);
    }
  }

  function _startPolling() {
    if (_pollTimer) return;
    _fetchQueue();
    _pollTimer = setInterval(_fetchQueue, 3000);
  }

  /* 동기 읽기 — analyze() 등 내부 호출 전용 */
  function loadQueue() {
    return _cache;
  }

  /* 비동기 저장 — 캐시 즉시 갱신 후 백엔드 동기화 */
  async function saveQueue(newQ) {
    const prevMap = new Map(_cache.map(p => [p.id, p]));
    const newIds  = new Set(newQ.map(p => p.id));

    _cache = newQ;
    window.dispatchEvent(new CustomEvent("rxassist:update"));

    /* 큐에서 빠진 환자 → done 처리 */
    for (const [id, p] of prevMap) {
      if (!newIds.has(id)) {
        _markDone(p).catch(() => {});
      }
    }

    /* 신규 환자 POST, 처방 변경 시 PATCH */
    for (const p of newQ) {
      const old = prevMap.get(p.id);
      if (!p._dbId) {
        await _createPatient(p);
      } else if (old && old.prescription !== p.prescription) {
        _patchPatient(p._dbId, {
          current_medications: {
            history:      p.history      || "",
            prescription: p.prescription || "",
          },
        }).catch(() => {});
      }
    }
  }

  function subscribe(cb) {
    window.addEventListener("rxassist:update", cb);
    _startPolling();
  }

  /* ===== 약물 DB (간이) ===== */
  const DRUG_DB = [
    // NSAIDs
    { key: "ibuprofen", names: ["ibuprofen", "이부프로펜"], class: "NSAID" },
    { key: "naproxen", names: ["naproxen", "나프록센"], class: "NSAID" },
    { key: "aceclofenac", names: ["aceclofenac", "아세클로페낙"], class: "NSAID" },
    { key: "diclofenac", names: ["diclofenac", "디클로페낙"], class: "NSAID" },
    { key: "celecoxib", names: ["celecoxib", "세레콕시브", "쎄레콕시브"], class: "COX2" },
    { key: "nsaid", names: ["nsaid", "nsaids"], class: "NSAID" },
    // 진통제
    { key: "acetaminophen", names: ["acetaminophen", "아세트아미노펜", "tylenol", "타이레놀", "paracetamol"], class: "진통제" },
    { key: "tramadol", names: ["tramadol", "트라마돌"], class: "opioid" },
    // 항생제
    { key: "ciprofloxacin", names: ["ciprofloxacin", "시프로플록사신"], class: "fluoroquinolone" },
    { key: "levofloxacin", names: ["levofloxacin", "레보플록사신"], class: "fluoroquinolone" },
    { key: "azithromycin", names: ["azithromycin", "아지트로마이신"], class: "macrolide" },
    { key: "clarithromycin", names: ["clarithromycin", "클래리트로마이신", "클라리트로마이신"], class: "macrolide" },
    { key: "amoxicillin", names: ["amoxicillin", "아목시실린"], class: "penicillin" },
    { key: "cefixime", names: ["cefixime", "세픽심"], class: "cephalosporin" },
    // 심혈관
    { key: "amlodipine", names: ["amlodipine", "암로디핀"], class: "CCB" },
    { key: "losartan", names: ["losartan", "로사르탄"], class: "ARB" },
    { key: "valsartan", names: ["valsartan", "발사르탄"], class: "ARB" },
    { key: "enalapril", names: ["enalapril", "에날라프릴"], class: "ACEI" },
    { key: "lisinopril", names: ["lisinopril", "리시노프릴"], class: "ACEI" },
    { key: "hydrochlorothiazide", names: ["hydrochlorothiazide", "hctz", "히드로클로로티아지드"], class: "thiazide" },
    { key: "spironolactone", names: ["spironolactone", "스피로노락톤"], class: "K-sparing" },
    { key: "propranolol", names: ["propranolol", "프로프라놀롤"], class: "betablocker" },
    // 당뇨
    { key: "metformin", names: ["metformin", "메트포르민"], class: "biguanide" },
    { key: "glimepiride", names: ["glimepiride", "글리메피리드"], class: "sulfonylurea" },
    { key: "empagliflozin", names: ["empagliflozin", "엠파글리플로진"], class: "SGLT2" },
    // 소화기
    { key: "omeprazole", names: ["omeprazole", "오메프라졸"], class: "PPI" },
    { key: "esomeprazole", names: ["esomeprazole", "에소메프라졸"], class: "PPI" },
    { key: "ranitidine", names: ["ranitidine", "라니티딘"], class: "H2RA" },
    // 정신과
    { key: "alprazolam", names: ["alprazolam", "알프라졸람"], class: "BZD" },
    { key: "lorazepam", names: ["lorazepam", "로라제팜"], class: "BZD" },
    { key: "diazepam", names: ["diazepam", "디아제팜"], class: "BZD" },
    { key: "sertraline", names: ["sertraline", "서트랄린"], class: "SSRI" },
    { key: "amitriptyline", names: ["amitriptyline", "아미트립틸린"], class: "TCA" },
    // 항응고
    { key: "warfarin", names: ["warfarin", "와파린"], class: "anticoagulant" },
    { key: "aspirin", names: ["aspirin", "아스피린"], class: "antiplatelet" },
    // 항히스타민
    { key: "chlorpheniramine", names: ["chlorpheniramine", "클로르페니라민"], class: "antihistamine-1gen" },
    { key: "cetirizine", names: ["cetirizine", "세티리진"], class: "antihistamine-2gen" },
    // 근이완제
    { key: "eperisone", names: ["eperisone", "에페리손"], class: "muscle-relaxant" },
    // 스테로이드
    { key: "prednisolone", names: ["prednisolone", "프레드니솔론"], class: "steroid" },
    // 당뇨 — SGLT2i (추가)
    { key: "dapagliflozin",  names: ["dapagliflozin",  "다파글리플로진"],  class: "SGLT2" },
    { key: "canagliflozin",  names: ["canagliflozin",  "카나글리플로진"],  class: "SGLT2" },
    // 당뇨 — DPP-4
    { key: "sitagliptin",    names: ["sitagliptin",    "시타글립틴"],      class: "DPP4" },
    { key: "linagliptin",    names: ["linagliptin",    "리나글립틴"],      class: "DPP4" },
    { key: "vildagliptin",   names: ["vildagliptin",   "빌다글립틴"],      class: "DPP4" },
    { key: "saxagliptin",    names: ["saxagliptin",    "삭사글립틴"],      class: "DPP4" },
    // 당뇨 — GLP-1
    { key: "liraglutide",    names: ["liraglutide",    "리라글루티드",   "빅토자"],   class: "GLP1" },
    { key: "semaglutide",    names: ["semaglutide",    "세마글루티드",   "오젬픽"],   class: "GLP1" },
    { key: "dulaglutide",    names: ["dulaglutide",    "둘라글루티드",   "트루리시티"], class: "GLP1" },
    // 당뇨 — 설포닐우레아 추가
    { key: "gliclazide",     names: ["gliclazide",     "글리클라지드"],    class: "sulfonylurea" },
    // 지질 — Statins
    { key: "rosuvastatin",   names: ["rosuvastatin",   "로수바스타틴"],    class: "statin" },
    { key: "atorvastatin",   names: ["atorvastatin",   "아토르바스타틴"],  class: "statin" },
    { key: "simvastatin",    names: ["simvastatin",    "심바스타틴"],      class: "statin" },
    { key: "pravastatin",    names: ["pravastatin",    "프라바스타틴"],    class: "statin" },
    { key: "pitavastatin",   names: ["pitavastatin",   "피타바스타틴"],    class: "statin" },
    // 항응고 — NOAC
    { key: "apixaban",       names: ["apixaban",       "아픽사반",  "엘리퀴스"],  class: "NOAC" },
    { key: "rivaroxaban",    names: ["rivaroxaban",    "리바록사반","자렐토"],    class: "NOAC" },
    { key: "dabigatran",     names: ["dabigatran",     "다비가트란","프라닥사"],  class: "NOAC" },
    { key: "edoxaban",       names: ["edoxaban",       "에독사반",  "릭시아나"],  class: "NOAC" },
    // 심혈관 — 선택적 β1차단제
    { key: "bisoprolol",     names: ["bisoprolol",     "비소프롤롤"],      class: "betablocker-selective" },
    { key: "carvedilol",     names: ["carvedilol",     "카르베딜롤"],      class: "betablocker" },
    { key: "metoprolol",     names: ["metoprolol",     "메토프롤롤"],      class: "betablocker-selective" },
    // 심혈관 — ARNI
    { key: "sacubitril_valsartan", names: ["sacubitril", "사쿠비트릴", "엔트레스토"], class: "ARNI" },
    // 심혈관 — MRA
    { key: "eplerenone",     names: ["eplerenone",     "에플레레논"],      class: "K-sparing" },
    // 통풍 — ULT
    { key: "allopurinol",    names: ["allopurinol",    "알로퓨리놀"],      class: "urate-lowering" },
    { key: "febuxostat",     names: ["febuxostat",     "페북소스타트"],    class: "urate-lowering" },
    // 호흡기 — 기관지확장제
    { key: "tiotropium",     names: ["tiotropium",     "티오트로피움"],    class: "LAMA" },
    { key: "formoterol",     names: ["formoterol",     "포르모테롤"],      class: "LABA" },
    { key: "salmeterol",     names: ["salmeterol",     "살메테롤"],        class: "LABA" },
    { key: "salbutamol",     names: ["salbutamol",     "살부타몰", "albuterol", "알부테롤"], class: "SABA" },
    // 정신과 — SNRI
    { key: "duloxetine",     names: ["duloxetine",     "둘록세틴"],        class: "SNRI" },
    { key: "venlafaxine",    names: ["venlafaxine",    "벤라팍신"],        class: "SNRI" },
  ];

  function parseDrug(line) {
    const raw = line.trim();
    if (!raw) return null;
    const lower = raw.toLowerCase();
    const found = DRUG_DB.find(d => d.names.some(n => lower.includes(n.toLowerCase())));
    if (!found) return null;  // DB에 없는 약물명·일반 텍스트는 무시

    const strMatch = raw.match(/(\d+(?:\.\d+)?)\s*(mg|mcg|g|unit|iu|㎎)/i);
    const doseMatch = raw.match(/\b(qd|bid|tid|qid|qhs|prn|q\d+h|아침|저녁|식후|식전)\b/i);

    return {
      raw,
      name: found.names[0].toUpperCase().slice(0,1) + found.names[0].slice(1),
      key: found.key,
      drugClass: found.class,
      strength: strMatch ? strMatch[0] : "",
      dose: doseMatch ? doseMatch[0] : "",
    };
  }

  /* ===== 상호작용 / 금기 규칙 ===== */
  const RULES = [
    (p, d) => (d.drugClass === "NSAID" || d.drugClass === "COX2") && p.labs?.eGFR && p.labs.eGFR < 60
      ? { sev: p.labs.eGFR < 30 ? "critical" : "high", reason: `CKD(eGFR ${p.labs.eGFR})에서 신기능 악화 위험`, evidence: "KDIGO 2024" } : null,
    (p, d) => (d.drugClass === "NSAID" || d.drugClass === "COX2") && p.baseDiseases?.includes("만성신장병(CKD)")
      ? { sev: "high", reason: "CKD 병력 — 신기능 악화 위험", evidence: "KDIGO 2024" } : null,

    (p, d) => (d.drugClass === "NSAID" || d.drugClass === "COX2") && p.baseDiseases?.includes("소화성궤양")
      ? { sev: "high", reason: "소화성궤양 병력 — GI 출혈 위험", evidence: "KASL 2023" } : null,

    (p, d) => (d.drugClass === "NSAID" || d.drugClass === "COX2") && p.baseDiseases?.includes("심부전")
      ? { sev: "critical", reason: "심부전 — 체액저류·악화 유발", evidence: "ESC 2023" } : null,

    (p, d) => (d.drugClass === "NSAID" || d.drugClass === "COX2") && p.pregnant
      ? { sev: "critical", reason: "임신 (특히 20주 이후) — 금기", evidence: "FDA 2020" } : null,

    (p, d) => d.key === "metformin" && p.labs?.eGFR && p.labs.eGFR < 30
      ? { sev: "critical", reason: `eGFR ${p.labs.eGFR} — 락트산산증 위험 (금기)`, evidence: "FDA 2016" } : null,
    (p, d) => d.key === "metformin" && p.labs?.eGFR && p.labs.eGFR >= 30 && p.labs.eGFR < 45
      ? { sev: "warn", reason: `eGFR ${p.labs.eGFR} — 용량 감량 고려 (50%)`, evidence: "FDA 2016" } : null,

    (p, d) => (d.drugClass === "ACEI" || d.drugClass === "ARB") && p.labs?.K && p.labs.K > 5.0
      ? { sev: "high", reason: `고칼륨혈증 (K⁺ ${p.labs.K}) — 악화 위험`, evidence: "KDIGO 2024" } : null,

    (p, d, all) => d.drugClass === "K-sparing" && all.some(x => x.drugClass === "ACEI" || x.drugClass === "ARB")
      ? { sev: "high", reason: "ACEI/ARB 병용 — 고칼륨혈증 위험", evidence: "Lexicomp" } : null,

    (p, d) => d.drugClass === "fluoroquinolone" && p.labs?.QTc && p.labs.QTc > 450
      ? { sev: "critical", reason: `QTc ${p.labs.QTc}ms — QT 연장 (금기 수준)`, evidence: "CredibleMeds" } : null,
    (p, d) => d.drugClass === "fluoroquinolone" && p.age >= 65
      ? { sev: "warn", reason: "고령 — 건증/건파열 위험", evidence: "FDA 2016" } : null,

    (p, d) => d.drugClass === "macrolide" && p.labs?.QTc && p.labs.QTc > 450
      ? { sev: "high", reason: `QTc ${p.labs.QTc}ms — QT 연장 가능`, evidence: "CredibleMeds" } : null,

    (p, d) => d.drugClass === "BZD" && p.age >= 65
      ? { sev: "high", reason: "고령 — Beers 기준 PIM (낙상·섬망)", evidence: "Beers 2023" } : null,

    (p, d) => d.drugClass === "TCA" && p.age >= 65
      ? { sev: "high", reason: "고령 — Beers 기준 PIM (항콜린성)", evidence: "Beers 2023" } : null,
    (p, d) => d.drugClass === "TCA" && p.baseDiseases?.includes("전립선비대")
      ? { sev: "high", reason: "전립선비대 — 요저류 위험", evidence: "Beers 2023" } : null,
    (p, d) => d.drugClass === "TCA" && p.baseDiseases?.includes("녹내장")
      ? { sev: "high", reason: "녹내장 — 안압 상승 위험", evidence: "Beers 2023" } : null,

    (p, d) => d.drugClass === "antihistamine-1gen" && p.age >= 65
      ? { sev: "high", reason: "고령 — Beers 기준 PIM (인지·낙상)", evidence: "Beers 2023" } : null,

    (p, d) => d.key === "propranolol" && p.baseDiseases?.includes("천식·COPD")
      ? { sev: "critical", reason: "천식·COPD — 기관지 수축 (금기)", evidence: "GOLD 2024" } : null,

    (p, d) => {
      if (!p.allergies || !p.allergies.length) return null;
      const hit = p.allergies.find(a => a && d.raw.toLowerCase().includes(a.toLowerCase().split(/[\s(]/)[0]));
      return hit ? { sev: "critical", reason: `알러지 이력 (${hit})`, evidence: "환자 문진" } : null;
    },

    (p, d, all) => d.key === "warfarin" && all.some(x => x.drugClass === "NSAID" || x.key === "aspirin")
      ? { sev: "high", reason: "NSAID/aspirin 병용 — 출혈 위험", evidence: "Lexicomp" } : null,

    (p, d) => d.drugClass === "PPI" && p.age >= 65
      ? { sev: "warn", reason: "장기 사용 시 골절·C.diff 위험 모니터", evidence: "Beers 2023" } : null,

    (p, d) => p.pregnant && (d.drugClass === "ACEI" || d.drugClass === "ARB")
      ? { sev: "critical", reason: "임신 — 태아기형 (금기)", evidence: "FDA pregnancy" } : null,
    (p, d) => p.pregnant && d.drugClass === "fluoroquinolone"
      ? { sev: "critical", reason: "임신 — 연골 발달 영향 (금기)", evidence: "FDA pregnancy" } : null,

    /* ── 추가 GDMT 기반 부정적 규칙 ─────────────────────────── */
    // 티아지드 + 통풍
    (p, d) => d.drugClass === "thiazide" && p.baseDiseases?.includes("통풍")
      ? { sev: "high", reason: "통풍 환자 — 티아지드 이뇨제는 요산 상승·발작 유발", evidence: "ACR 2020" } : null,

    // NSAID + 고혈압 (혈압 상승·항고혈압 효과 감소)
    (p, d) => (d.drugClass === "NSAID" || d.drugClass === "COX2") && p.baseDiseases?.includes("고혈압")
      ? { sev: "warn", reason: "고혈압 — NSAID는 혈압 상승·항고혈압제 효과 감소 유발", evidence: "ACC/AHA 2023" } : null,

    // NSAID + 항응고제 병용 (출혈 위험 증가)
    (p, d, all) => (d.drugClass === "NSAID" || d.drugClass === "COX2") && all.some(x => x.drugClass === "anticoagulant" || x.drugClass === "NOAC")
      ? { sev: "high", reason: "항응고제 병용 — GI 출혈 위험 2–3배 증가", evidence: "Lexicomp" } : null,

    // NSAID + 아스피린 병용 시 PPI 미처방 경고
    (p, d, all) => d.drugClass === "NSAID" && all.some(x => x.key === "aspirin") && !all.some(x => x.drugClass === "PPI")
      ? { sev: "warn", reason: "아스피린 병용 시 PPI 미처방 — GI 출혈 예방 위해 PPI 병용 권장", evidence: "KASL 2023" } : null,

    // 설포닐우레아 + 고령 (저혈당 고위험)
    (p, d) => d.drugClass === "sulfonylurea" && p.age >= 65
      ? { sev: "warn", reason: "고령 — 설포닐우레아 저혈당 위험 증가 (Beers 2023 주의 약물)", evidence: "Beers 2023 / ADA 2026" } : null,

    // 비선택적 β차단제 + 당뇨 (저혈당 증상 마스킹)
    (p, d) => d.key === "propranolol" && p.baseDiseases?.includes("당뇨병")
      ? { sev: "warn", reason: "당뇨병 — 비선택적 β차단제는 저혈당 증상(빈맥) 마스킹", evidence: "ACC/AHA 2023" } : null,

    // 플루오로퀴놀론 + 항응고제 (INR 상승)
    (p, d, all) => d.drugClass === "fluoroquinolone" && all.some(x => x.drugClass === "anticoagulant" || x.drugClass === "NOAC")
      ? { sev: "high", reason: "항응고제 병용 — CYP2C9 억제로 INR 상승·출혈 위험 증가", evidence: "Lexicomp" } : null,

    // 마크로라이드 + 항응고제 (INR 상승)
    (p, d, all) => d.drugClass === "macrolide" && all.some(x => x.drugClass === "anticoagulant")
      ? { sev: "high", reason: "와파린 병용 — CYP3A4 억제로 INR 상승·출혈 위험", evidence: "Lexicomp" } : null,

    // Statin + 마크로라이드 (근병증 위험)
    (p, d, all) => d.drugClass === "statin" && all.some(x => x.drugClass === "macrolide")
      ? { sev: "warn", reason: "마크로라이드 병용 — CYP3A4 억제로 Statin 혈중농도↑·근병증 위험", evidence: "Lexicomp" } : null,

    // 티아지드 + 저나트륨 고령 (심각한 저나트륨 위험)
    (p, d) => d.drugClass === "thiazide" && p.age >= 65 && p.labs?.Na && p.labs.Na < 136
      ? { sev: "high", reason: `저나트륨혈증(Na⁺ ${p.labs.Na}) + 고령 + 티아지드 — 생명위협 저나트륨 위험`, evidence: "Beers 2023" } : null,

    // ACEI/ARB + 고칼륨혈증 + MRA 병용
    (p, d, all) => (d.drugClass === "ACEI" || d.drugClass === "ARB") && all.some(x => x.drugClass === "K-sparing") && p.labs?.K && p.labs.K > 4.5
      ? { sev: "high", reason: `K⁺ ${p.labs.K} 상승 추세 + MRA 병용 — 고칼륨혈증 급격 악화 가능`, evidence: "KDIGO 2024" } : null,

    // GLP-1 + 췌장염 병력 (아직 환자 필드 없으나 예비 규칙)
    (p, d) => d.drugClass === "GLP1" && p.baseDiseases?.includes("간질환")
      ? { sev: "warn", reason: "간질환 — GLP-1 효과 변동 가능, 간수치 모니터 권고", evidence: "ADA 2026" } : null,

    // NOAC + 심한 신기능 저하
    (p, d) => d.drugClass === "NOAC" && p.labs?.eGFR && p.labs.eGFR < 15
      ? { sev: "critical", reason: `eGFR ${p.labs.eGFR} — 대부분 NOAC 금기 (와파린으로 전환 검토)`, evidence: "ESC 2023 AF" } : null,
    (p, d) => d.drugClass === "NOAC" && p.labs?.eGFR && p.labs.eGFR >= 15 && p.labs.eGFR < 30
      ? { sev: "high", reason: `eGFR ${p.labs.eGFR} — NOAC 용량 감량 또는 와파린 전환 검토 필요`, evidence: "ESC 2023 AF" } : null,

    // Metformin + eGFR 30~45 (조기 경고)
    (p, d) => d.key === "metformin" && p.labs?.eGFR && p.labs.eGFR >= 30 && p.labs.eGFR < 45
      ? { sev: "warn", reason: `eGFR ${p.labs.eGFR} — Metformin 50% 감량 및 신기능 모니터 필요`, evidence: "ADA 2026 / FDA 2016" } : null,

    // 스테로이드 + 당뇨 (혈당 상승)
    (p, d) => d.drugClass === "steroid" && p.baseDiseases?.includes("당뇨병")
      ? { sev: "warn", reason: "당뇨병 — 스테로이드는 혈당 급격 상승 유발, 용량·기간 최소화", evidence: "ADA 2026" } : null,

    // 스테로이드 + 고혈압 (체액저류)
    (p, d) => d.drugClass === "steroid" && p.baseDiseases?.includes("고혈압")
      ? { sev: "warn", reason: "고혈압 — 스테로이드는 나트륨·수분 저류로 혈압 상승 유발", evidence: "ACC/AHA 2023" } : null,
  ];

  /* ===== Clinical Evidence 데이터베이스 (RULES evidence 키 → 근거 상세) ===== */
  const CLINICAL_EVIDENCE_DB = {
    "KDIGO 2024": {
      rationale: "KDIGO 2024 만성신장질환(CKD) 관리 가이드라인에 근거합니다. 신독성 약물(NSAID 등)은 사구체 혈역학을 교란하여 GFR 저하를 가속화하며, eGFR 단계에 따른 금기·용량 조정이 필수입니다.",
      refs: [
        { label: "KDIGO 2024 CKD Guideline", url: "https://kdigo.org/guidelines/ckd-evaluation-and-management/" }
      ]
    },
    "KASL 2023": {
      rationale: "대한소화기학회(KASL) 2023 가이드라인에 근거합니다. NSAID는 위장 점막 프로스타글란딘을 억제하여 소화성궤양·GI 출혈 위험을 2–5배 증가시킵니다.",
      refs: [
        { label: "Lanza 2009 — NSAID GI Risk Guidelines (PMID 19177184)", pmid: "19177184" }
      ]
    },
    "ESC 2023": {
      rationale: "ESC 2023 심부전 가이드라인에 근거합니다. NSAID는 나트륨·수분 저류를 유발하여 심부전을 급격히 악화시키며, 재입원 및 사망 위험을 증가시킵니다.",
      refs: [
        { label: "McDonagh 2021 — ESC 2021 HF Guidelines (PMID 34447992)", pmid: "34447992", doi: "10.1093/eurheartj/ehab368" }
      ]
    },
    "FDA 2020": {
      rationale: "FDA 2020 임신 안전성 경고에 근거합니다. NSAID는 임신 20주 이후 태아 신장 프로스타글란딘 합성을 억제하여 양수과소증 및 태아 신독성을 초래할 수 있습니다.",
      refs: [
        { label: "FDA Safety Communication 2020 — NSAIDs in Pregnancy", url: "https://www.fda.gov/drugs/drug-safety-and-availability/fda-recommends-avoiding-use-nsaids-pregnancy-20-weeks-or-later" }
      ]
    },
    "FDA 2016": {
      rationale: "FDA 2016 라벨 업데이트에 근거합니다. 해당 약물은 신기능 저하 또는 특정 연령대에서 심각한 부작용이 확인되어 용량 조정 또는 사용 금기가 권고됩니다.",
      refs: [
        { label: "FDA Drug Safety Communication 2016", url: "https://www.fda.gov/drugs/drug-safety-and-availability" }
      ]
    },
    "Lexicomp": {
      rationale: "Lexicomp 약물 상호작용 데이터베이스에 근거합니다. 해당 약물 병용은 CYP 효소 억제·단백 결합 경쟁 등 약동학적 상호작용으로 독성 또는 출혈 위험을 유의하게 증가시킵니다.",
      refs: [
        { label: "Lexicomp Drug Interactions — Wolters Kluwer", url: "https://www.wolterskluwer.com/en/solutions/lexicomp" }
      ]
    },
    "CredibleMeds": {
      rationale: "CredibleMeds(QTDrugs) 데이터베이스에 근거합니다. 해당 약물은 hERG 채널 차단을 통해 QT 연장·Torsades de Pointes 위험이 'Known Risk'로 분류되어 있습니다.",
      refs: [
        { label: "CredibleMeds QTDrugs List — Arizona CERT", url: "https://crediblemeds.org/" },
        { label: "Roden 2004 — Drug-induced QT Prolongation (PMID 14734743)", pmid: "14734743" }
      ]
    },
    "Beers 2023": {
      rationale: "미국노인의학회(AGS) Beers Criteria 2023에 근거합니다. 해당 약물은 고령(≥65세)에서 낙상·섬망·인지기능 저하·항콜린성 부작용 등 잠재적 부적절 약물(PIM)로 분류됩니다.",
      refs: [
        { label: "AGS Beers Criteria 2023 (PMID 37139824)", pmid: "37139824", doi: "10.1111/jgs.18372" }
      ]
    },
    "GOLD 2024": {
      rationale: "GOLD(Global Initiative for Chronic Obstructive Lung Disease) 2024 보고서에 근거합니다. 비선택적 β차단제는 기관지 평활근 β2 수용체를 차단하여 COPD·천식 환자에서 급성 기관지 수축 및 악화를 유발합니다.",
      refs: [
        { label: "GOLD 2024 COPD Report", url: "https://goldcopd.org/2024-gold-report/" }
      ]
    },
    "환자 문진": {
      rationale: "환자 문진에서 확인된 약물 알레르기 이력에 근거합니다. 알레르기 반응은 아나필락시스 등 생명위협 반응을 초래할 수 있어 해당 성분 및 교차반응 약물 처방을 금지합니다.",
      refs: []
    },
    "FDA pregnancy": {
      rationale: "FDA 임신 안전성 분류 및 기형유발 데이터에 근거합니다. 해당 약물은 임신 중 태아 기형·손상 위험이 확인되어 임신 전 기간에 걸쳐 원칙적으로 금기입니다.",
      refs: [
        { label: "Briggs — Drugs in Pregnancy and Lactation (Reference Textbook)" }
      ]
    },
    "ACC/AHA 2023": {
      rationale: "ACC/AHA 2023 고혈압·심혈관 가이드라인에 근거합니다. NSAID·스테로이드 등은 신장 내 프로스타글란딘 억제로 나트륨 저류·혈압 상승을 유발하며 항고혈압제 효과를 약화시킵니다.",
      refs: [
        { label: "Whelton 2018 — ACC/AHA Hypertension Guideline (PMID 29133354)", pmid: "29133354" }
      ]
    },
    "ACR 2020": {
      rationale: "미국류마티스학회(ACR) 2020 통풍 가이드라인에 근거합니다. 티아지드 이뇨제는 요세관에서 요산 재흡수를 증가시켜 혈중 요산을 상승시키고 통풍 발작을 유발합니다.",
      refs: [
        { label: "FitzGerald 2020 — ACR 2020 Gout Guidelines (PMID 33938884)", pmid: "33938884", doi: "10.1002/art.41247" }
      ]
    },
    "Beers 2023 / ADA 2026": {
      rationale: "AGS Beers Criteria 2023 및 ADA 2026 당뇨병 표준진료에 근거합니다. 설포닐우레아는 고령 환자에서 지속성 저혈당 위험이 증가하며, ADA는 안전성 높은 DPP-4 억제제·SGLT2i를 우선 권고합니다.",
      refs: [
        { label: "AGS Beers Criteria 2023 (PMID 37139824)", pmid: "37139824" },
        { label: "ADA 2026 Standards of Diabetes Care", url: "https://diabetesjournals.org/care/issue/49/Supplement_1" }
      ]
    },
    "ADA 2026": {
      rationale: "ADA 2026 당뇨병 표준진료에 근거합니다. 혈당 조절 약물 선택 시 동반 질환(CKD, 심부전, 간질환), 저혈당 위험, 체중 영향, 심혈관 보호 효과를 종합적으로 고려해야 합니다.",
      refs: [
        { label: "ADA 2026 Standards of Diabetes Care", url: "https://diabetesjournals.org/care/issue/49/Supplement_1" }
      ]
    },
    "ESC 2023 AF": {
      rationale: "ESC 2023 심방세동 가이드라인에 근거합니다. NOAC은 신기능에 따라 용량을 조정해야 하며, eGFR < 15 mL/min에서 대부분 금기이므로 와파린으로의 전환을 검토합니다.",
      refs: [
        { label: "Van Gelder 2024 — ESC 2023 AF Guideline (PMID 37622599)", pmid: "37622599", doi: "10.1093/eurheartj/ehad222" }
      ]
    },
    "ADA 2026 / FDA 2016": {
      rationale: "ADA 2026 가이드라인 및 FDA 2016 라벨 업데이트에 근거합니다. Metformin은 eGFR 30~45에서 50% 감량, eGFR < 30에서 금기이며 신기능 주기적 모니터가 필수입니다.",
      refs: [
        { label: "ADA 2026 Standards of Diabetes Care", url: "https://diabetesjournals.org/care/issue/49/Supplement_1" },
        { label: "FDA 2016 — Metformin Labeling Update", url: "https://www.fda.gov/drugs/drug-safety-and-availability/fda-drug-safety-communication-fda-revises-warnings-regarding-use-diabetes-medicine-metformin-certain" }
      ]
    },
  };

  /* ===== GDMT Clinical Evidence 데이터베이스 ===== */
  const _GDMT_RULE_EVKEY = [
    "HF_ACEI_ARB",       // 0 — 심부전 ACEi/ARB
    "HF_BETA_BLOCKER",   // 1 — 심부전 β차단제
    "HF_MRA",            // 2 — 심부전 MRA
    "HF_SGLT2I",         // 3 — 심부전 SGLT2i
    "DM_CKD_SGLT2I",     // 4 — T2DM+CKD SGLT2i
    "DM_CKD_LINA",       // 5 — T2DM+CKD Linagliptin
    "DM_METFORMIN",      // 6 — T2DM Metformin
    "DM_CVD_SGLT2_GLP1", // 7 — T2DM+CVD SGLT2/GLP-1
    "HTN_DM_CKD_RAAS",   // 8 — 고혈압+DM/CKD RAAS
    "AF_NOAC",           // 9 — 심방세동 NOAC
    "CKD_RAAS",          // 10 — CKD RAAS
    "STATIN_CVD",        // 11 — 고지혈증/CVD Statin
    "GOUT_ALLOPURINOL",  // 12 — 통풍 Allopurinol
    "COPD_LAMA_LABA",    // 13 — COPD LAMA/LABA
  ];

  const GDMT_EVIDENCE_DB = {
    "HF_ACEI_ARB": {
      rationale: "ACC/AHA 2023 심부전 가이드라인 및 SOLVD(1991), PARADIGM-HF(2014) 연구에 근거합니다. ACEi/ARB는 HFrEF에서 전사망률을 16~17% 감소시키며, ARNI(Sacubitril/Valsartan)는 Enalapril 대비 사망·입원을 추가 20% 감소시킵니다.",
      refs: [
        { label: "SOLVD 1991 — Enalapril in Heart Failure (PMID 1955909)", pmid: "1955909" },
        { label: "McMurray 2014 — PARADIGM-HF (PMID 25176015)", pmid: "25176015", doi: "10.1056/NEJMoa1409077" }
      ]
    },
    "HF_BETA_BLOCKER": {
      rationale: "ACC/AHA 2023 가이드라인 및 CIBIS-II(1999), MERIT-HF(1999), COPERNICUS(2001) 연구에 근거합니다. HFrEF에서 선택적 β1차단제는 심혈관 사망률을 34~65% 감소시키며 심근 리모델링을 억제합니다.",
      refs: [
        { label: "CIBIS-II 1999 — Bisoprolol in Heart Failure (PMID 9922003)", pmid: "9922003" },
        { label: "MERIT-HF 1999 — Metoprolol Succinate in HF (PMID 10381652)", pmid: "10381652" },
        { label: "Packer 2001 — COPERNICUS: Carvedilol (PMID 11394097)", pmid: "11394097" }
      ]
    },
    "HF_MRA": {
      rationale: "ACC/AHA 2023 가이드라인 및 RALES(1999), EMPHASIS-HF(2011) 연구에 근거합니다. MRA(Spironolactone/Eplerenone)는 HFrEF에서 전사망률을 30%, 심혈관 사망·입원을 37% 감소시킵니다. K⁺ 및 신기능 모니터 필수.",
      refs: [
        { label: "Pitt 1999 — RALES: Spironolactone in HF (PMID 10471456)", pmid: "10471456", doi: "10.1056/NEJM199909023411001" },
        { label: "Zannad 2011 — EMPHASIS-HF: Eplerenone (PMID 21073363)", pmid: "21073363", doi: "10.1056/NEJMoa1009492" }
      ]
    },
    "HF_SGLT2I": {
      rationale: "ACC/AHA 2023 가이드라인 및 DAPA-HF(2019), EMPEROR-Reduced(2020) 연구에 근거합니다. SGLT2i는 HFrEF/HFpEF 모두에서 심혈관 사망·심부전 입원을 25~26% 감소시키며, 당뇨 유무와 무관하게 효과가 있습니다.",
      refs: [
        { label: "McMurray 2019 — DAPA-HF (PMID 31535829)", pmid: "31535829", doi: "10.1056/NEJMoa1911303" },
        { label: "Packer 2020 — EMPEROR-Reduced (PMID 32865377)", pmid: "32865377", doi: "10.1056/NEJMoa2022190" }
      ]
    },
    "DM_CKD_SGLT2I": {
      rationale: "ADA 2026 및 KDIGO 2024 가이드라인, EMPA-KIDNEY(2023), CREDENCE(2019) 연구에 근거합니다. SGLT2i는 T2DM+CKD에서 신기능 저하(GFR 감소)를 25~40% 억제하고 투석·사망 위험을 유의하게 낮춥니다.",
      refs: [
        { label: "Herrington 2023 — EMPA-KIDNEY (PMID 36331190)", pmid: "36331190", doi: "10.1056/NEJMoa2204233" },
        { label: "Perkovic 2019 — CREDENCE (PMID 30990260)", pmid: "30990260", doi: "10.1056/NEJMoa1811744" }
      ]
    },
    "DM_CKD_LINA": {
      rationale: "ADA 2026 및 KDIGO 2024 가이드라인에 근거합니다. Linagliptin은 간 경로로 대사되어 eGFR < 30에서도 용량 조정이 불필요한 유일한 DPP-4 억제제이며, 신기능 보호 안전성이 확립되어 있습니다.",
      refs: [
        { label: "Groop 2013 — Linagliptin + CKD Safety (PMID 23735230)", pmid: "23735230" },
        { label: "ADA 2026 Pharmacologic Approaches Section", url: "https://diabetesjournals.org/care/issue/49/Supplement_1" }
      ]
    },
    "DM_METFORMIN": {
      rationale: "ADA 2026 가이드라인 및 UKPDS 34(1998) 연구에 근거합니다. Metformin은 T2DM 1단계 기저 치료로 체중 중립·저혈당 없음·심혈관 안전성이 확립되어 있으며, 당뇨병 관련 사망을 36% 감소시켰습니다.",
      refs: [
        { label: "UKPDS 34 1998 — Metformin in T2DM (PMID 9742977)", pmid: "9742977" },
        { label: "ADA 2026 Standards of Diabetes Care", url: "https://diabetesjournals.org/care/issue/49/Supplement_1" }
      ]
    },
    "DM_CVD_SGLT2_GLP1": {
      rationale: "ADA 2026 가이드라인 및 EMPA-REG OUTCOME(2015), LEADER(2016), SUSTAIN-6(2016) 연구에 근거합니다. T2DM + ASCVD 환자에서 SGLT2i/GLP-1RA는 MACE(심혈관 사망·심근경색·뇌졸중)를 14~26% 감소시킵니다.",
      refs: [
        { label: "Zinman 2015 — EMPA-REG OUTCOME (PMID 26378978)", pmid: "26378978", doi: "10.1056/NEJMoa1504720" },
        { label: "Marso 2016 — LEADER: Liraglutide (PMID 27295427)", pmid: "27295427", doi: "10.1056/NEJMoa1603827" },
        { label: "Marso 2016 — SUSTAIN-6: Semaglutide (PMID 27633186)", pmid: "27633186" }
      ]
    },
    "HTN_DM_CKD_RAAS": {
      rationale: "ACC/AHA 2023 및 대한고혈압학회 2023 가이드라인, RENAAL(2001), IDNT(2001) 연구에 근거합니다. DM·CKD 동반 고혈압에서 ACEi/ARB는 신기능 저하 및 ESRD 진행을 25~28% 억제합니다.",
      refs: [
        { label: "Brenner 2001 — RENAAL: Losartan (PMID 11565518)", pmid: "11565518" },
        { label: "Lewis 2001 — IDNT: Irbesartan (PMID 11565517)", pmid: "11565517" }
      ]
    },
    "AF_NOAC": {
      rationale: "ACC/AHA/ESC 2023 심방세동 가이드라인 및 RE-LY(2009), ROCKET-AF(2011), ARISTOTLE(2011) 연구에 근거합니다. NOAC은 와파린 대비 뇌졸중 예방 효과가 동등하거나 우수하면서 두개내 출혈 위험을 50% 감소시킵니다.",
      refs: [
        { label: "Connolly 2009 — RE-LY: Dabigatran (PMID 19717844)", pmid: "19717844" },
        { label: "Patel 2011 — ROCKET-AF: Rivaroxaban (PMID 21830957)", pmid: "21830957" },
        { label: "Granger 2011 — ARISTOTLE: Apixaban (PMID 21870978)", pmid: "21870978" }
      ]
    },
    "CKD_RAAS": {
      rationale: "KDIGO 2024 CKD 가이드라인에 근거합니다. 단백뇨 동반 CKD에서 ACEi/ARB는 사구체내압을 감소시켜 신기능 저하 진행을 억제하며, 단백뇨를 30~40% 감소시킵니다.",
      refs: [
        { label: "KDIGO 2024 CKD Guideline", url: "https://kdigo.org/guidelines/ckd-evaluation-and-management/" },
        { label: "Jafar 2001 — ACE inhibition in CKD (PMID 11242047)", pmid: "11242047" }
      ]
    },
    "STATIN_CVD": {
      rationale: "ACC/AHA 2019 이상지질혈증 가이드라인 및 4S(1994), JUPITER(2008) 연구에 근거합니다. 중등도-고강도 Statin은 LDL을 50% 이상 감소시키며 심혈관 사건(심근경색·뇌졸중)을 25~35% 예방합니다.",
      refs: [
        { label: "4S 1994 — Simvastatin in CHD (PMID 7968073)", pmid: "7968073" },
        { label: "Ridker 2008 — JUPITER: Rosuvastatin (PMID 18997196)", pmid: "18997196", doi: "10.1056/NEJMoa0807646" }
      ]
    },
    "GOUT_ALLOPURINOL": {
      rationale: "ACR 2020 통풍 가이드라인에 근거합니다. 요산 강하 요법(ULT)은 재발성 통풍 관절염 예방에 필수이며, Allopurinol은 1차 권고 약물로 목표 요산 < 6.0 mg/dL 달성이 치료 기준입니다.",
      refs: [
        { label: "FitzGerald 2020 — ACR 2020 Gout Guidelines (PMID 33938884)", pmid: "33938884", doi: "10.1002/art.41247" }
      ]
    },
    "COPD_LAMA_LABA": {
      rationale: "GOLD 2024 COPD 보고서 및 UPLIFT(2008) 연구에 근거합니다. LAMA(Tiotropium)는 COPD 안정기 1차 권고 약물로 급성악화를 17% 감소시키며, 중증 COPD에서는 LABA/LAMA 이중 기관지확장제가 표준입니다.",
      refs: [
        { label: "Tashkin 2008 — UPLIFT: Tiotropium in COPD (PMID 18836213)", pmid: "18836213", doi: "10.1056/NEJMoa0805800" },
        { label: "GOLD 2024 COPD Report", url: "https://goldcopd.org/2024-gold-report/" }
      ]
    },
  };

  function enrichFinding(f) {
    if (!f || !f.evidence) return f;
    const ev = CLINICAL_EVIDENCE_DB[f.evidence];
    return ev ? { ...f, clinical_evidence: ev } : f;
  }

  /* ===== DDI 쌍별 상호작용 규칙 (복합처방 전수 체크) ===== */
  // rule(drugA, drugB) → finding | null  (순서 무관 — 내부에서 양방향 체크)
  const DDI_PAIR_RULES = [
    /* ── 동일 약물군 중복 ─────────────────────────────────── */
    (a, b) => ["NSAID","COX2"].includes(a.drugClass) && ["NSAID","COX2"].includes(b.drugClass)
      ? { sev:"critical", reason:`NSAID 중복 처방 (${a.name} + ${b.name}) — GI 출혈·신독성 위험 극대화, 단일 약제로 전환 필수`, evidence:"KASL 2023" } : null,

    (a, b) => a.drugClass === "statin" && b.drugClass === "statin"
      ? { sev:"critical", reason:`Statin 중복 (${a.name} + ${b.name}) — 횡문근융해증 위험 극대화 (병용 절대 금기)`, evidence:"Lexicomp" } : null,

    (a, b) => a.drugClass === "BZD" && b.drugClass === "BZD"
      ? { sev:"critical", reason:`BZD 중복 (${a.name} + ${b.name}) — 과진정·호흡억제·낙상 위험 (병용 금기)`, evidence:"Beers 2023" } : null,

    (a, b) => a.drugClass === "NOAC" && b.drugClass === "NOAC"
      ? { sev:"critical", reason:`NOAC 중복 (${a.name} + ${b.name}) — 치명적 출혈 위험 (병용 금기)`, evidence:"ESC 2023 AF" } : null,

    /* ── RAAS 이중 차단 ──────────────────────────────────── */
    (a, b) => (a.drugClass==="ACEI"&&b.drugClass==="ARB") || (a.drugClass==="ARB"&&b.drugClass==="ACEI")
      ? { sev:"critical", reason:`ACEI + ARB 이중 RAAS 차단 — 고칼륨혈증·급성신부전 위험 (ONTARGET: 이점 無, 유해성 입증)`, evidence:"KDIGO 2024" } : null,

    /* ── 항응고제 관련 ───────────────────────────────────── */
    (a, b) => (a.drugClass==="NOAC"&&b.drugClass==="anticoagulant") || (a.drugClass==="anticoagulant"&&b.drugClass==="NOAC")
      ? { sev:"critical", reason:`항응고제 중복 (${a.name} + ${b.name}) — 치명적 출혈 위험 (절대 병용 금기)`, evidence:"ESC 2023 AF" } : null,

    (a, b) => (["NSAID","COX2"].includes(a.drugClass)&&b.drugClass==="NOAC") || (["NSAID","COX2"].includes(b.drugClass)&&a.drugClass==="NOAC")
      ? { sev:"high", reason:`NSAID + NOAC — GI 출혈 위험 2~4배 증가 (점막 손상 + 항응고 상승), PPI 병용 강력 권고`, evidence:"Lexicomp" } : null,

    (a, b) => (["NSAID","COX2"].includes(a.drugClass)&&b.drugClass==="anticoagulant") || (["NSAID","COX2"].includes(b.drugClass)&&a.drugClass==="anticoagulant")
      ? { sev:"high", reason:`NSAID + 항응고제 — INR 불안정·혈소판 기능 억제·GI 점막 손상 삼중 출혈 위험`, evidence:"Lexicomp" } : null,

    (a, b) => (["NSAID","COX2"].includes(a.drugClass)&&b.key==="aspirin") || (["NSAID","COX2"].includes(b.drugClass)&&a.key==="aspirin")
      ? { sev:"high", reason:`NSAID + Aspirin 병용 — GI 출혈 위험 3~4배 가중, PPI 없으면 반드시 추가`, evidence:"KASL 2023" } : null,

    /* ── RAAS + K-저장 ───────────────────────────────────── */
    (a, b) => (["ACEI","ARB"].includes(a.drugClass)&&b.drugClass==="K-sparing") || (["ACEI","ARB"].includes(b.drugClass)&&a.drugClass==="K-sparing")
      ? { sev:"high", reason:`RAAS 차단제 + K-저장성 이뇨제 — 고칼륨혈증 위험, K⁺ 주 1회 이상 모니터 필수`, evidence:"KDIGO 2024" } : null,

    /* ── CYP450 약물 상호작용 ────────────────────────────── */
    (a, b) => (a.drugClass==="statin"&&b.drugClass==="macrolide") || (a.drugClass==="macrolide"&&b.drugClass==="statin")
      ? { sev:"high", reason:`Statin + Macrolide — CYP3A4 억제로 Statin 혈중농도 급상승, 근병증·횡문근융해증 위험`, evidence:"Lexicomp" } : null,

    (a, b) => (a.drugClass==="fluoroquinolone"&&b.drugClass==="anticoagulant") || (b.drugClass==="fluoroquinolone"&&a.drugClass==="anticoagulant")
      ? { sev:"high", reason:`Fluoroquinolone + 항응고제 — CYP2C9 억제로 INR 급상승·출혈 위험, INR 긴밀 모니터`, evidence:"Lexicomp" } : null,

    (a, b) => (a.drugClass==="macrolide"&&b.drugClass==="anticoagulant") || (a.drugClass==="anticoagulant"&&b.drugClass==="macrolide")
      ? { sev:"high", reason:`Macrolide + 항응고제 — CYP3A4 억제로 INR 상승·출혈 위험`, evidence:"Lexicomp" } : null,

    /* ── QT 연장 병용 ────────────────────────────────────── */
    (a, b) => (a.drugClass==="fluoroquinolone"&&b.drugClass==="macrolide") || (a.drugClass==="macrolide"&&b.drugClass==="fluoroquinolone")
      ? { sev:"critical", reason:`Fluoroquinolone + Macrolide — QT 연장 약물 병용, Torsades de Pointes(TdP) 위험 (심각한 부정맥)`, evidence:"CredibleMeds" } : null,

    (a, b) => (a.drugClass==="fluoroquinolone"&&b.drugClass==="TCA") || (a.drugClass==="TCA"&&b.drugClass==="fluoroquinolone")
      ? { sev:"high", reason:`Fluoroquinolone + TCA — QT 연장 상가 효과, TdP 위험`, evidence:"CredibleMeds" } : null,

    /* ── 신경·정신과 ─────────────────────────────────────── */
    (a, b) => (["SSRI","SNRI"].includes(a.drugClass)&&["NSAID","COX2"].includes(b.drugClass)) || (["SSRI","SNRI"].includes(b.drugClass)&&["NSAID","COX2"].includes(a.drugClass))
      ? { sev:"high", reason:`SSRI/SNRI + NSAID — 세로토닌성 혈소판 억제 + NSAID → 상부위장관 출혈 위험 OR 15.6배 (메타분석)`, evidence:"Lexicomp" } : null,

    (a, b) => (a.drugClass==="BZD"&&b.drugClass==="opioid") || (a.drugClass==="opioid"&&b.drugClass==="BZD")
      ? { sev:"critical", reason:`BZD + Opioid — FDA Black Box Warning: 호흡억제·사망 위험 (병용 최소화, 불가피 시 최저 용량)`, evidence:"FDA 2016" } : null,

    (a, b) => (a.drugClass==="fluoroquinolone"&&["NSAID","COX2"].includes(b.drugClass)) || (b.drugClass==="fluoroquinolone"&&["NSAID","COX2"].includes(a.drugClass))
      ? { sev:"warn", reason:`Fluoroquinolone + NSAID — GABA 수용체 길항 상가 효과, 경련 역치 감소 위험`, evidence:"Lexicomp" } : null,

    /* ── 혈압 관련 ───────────────────────────────────────── */
    (a, b) => (["betablocker","betablocker-selective"].includes(a.drugClass)&&["NSAID","COX2"].includes(b.drugClass)) || (["betablocker","betablocker-selective"].includes(b.drugClass)&&["NSAID","COX2"].includes(a.drugClass))
      ? { sev:"warn", reason:`베타차단제 + NSAID — 프로스타글란딘 억제로 항고혈압 효과 감소, 혈압 모니터 강화 필요`, evidence:"ACC/AHA 2023" } : null,
  ];

  /* DDI 전수 체크 — 모든 약물 쌍(i<j) 순회 */
  function checkDDI(drugs) {
    const findings = [];
    for (let i = 0; i < drugs.length; i++) {
      for (let j = i + 1; j < drugs.length; j++) {
        for (const rule of DDI_PAIR_RULES) {
          try {
            const f = rule(drugs[i], drugs[j]);
            if (f) findings.push({
              ...enrichFinding(f),
              drugA: drugs[i].name,
              drugB: drugs[j].name,
              type: "ddi",
            });
          } catch {}
        }
      }
    }
    return findings;
  }

  /* ===== GDMT 단계별 양성 권고 (분과별 학회 가이드라인) ===== */
  const _has = (p, d) => !!(p.baseDiseases?.includes(d));
  const _noDrug = (drugs, ...classes) => !drugs.some(d => classes.includes(d.drugClass) || classes.includes(d.key));
  const _egfr  = (p, min, max) => { const e = p.labs?.eGFR; return e != null ? (min == null || e >= min) && (max == null || e < max) : min == null; };

  const GDMT_POSITIVE_RULES = [
    /* ── 심부전 (ACC/AHA 2023 / ESC 2023 HF) ────────────────── */
    (p, drugs) => _has(p,"심부전") && _noDrug(drugs,"ACEI","ARB","ARNI") && !p.pregnant && !(p.labs?.K > 5.5)
      ? { specialty:"심혈관", guideline:"ACC/AHA 2023 HF 가이드라인", priority:1, action:"추가 검토",
          drug:"ACEi/ARB 또는 ARNI (예: Enalapril 5 mg BID · Valsartan 80 mg BID · 또는 Sacubitril/Valsartan 24/26 mg BID)",
          reason:"HFrEF GDMT 1단계 — RAAS 차단으로 사망률·재입원 유의하게 감소 (SOLVD, PARADIGM-HF)" } : null,

    (p, drugs) => _has(p,"심부전") && _noDrug(drugs,"betablocker","betablocker-selective") && !_has(p,"천식·COPD")
      ? { specialty:"심혈관", guideline:"ACC/AHA 2023 HF 가이드라인", priority:1, action:"추가 검토",
          drug:"선택적 β1차단제 (Bisoprolol 2.5 mg QD · Carvedilol 3.125 mg BID · Metoprolol succinate 25 mg QD)",
          reason:"HFrEF GDMT 1단계 — 심박수 조절·심근 리모델링 억제 (CIBIS-II, MERIT-HF)" } : null,

    (p, drugs) => _has(p,"심부전") && _noDrug(drugs,"K-sparing") && !(p.labs?.K > 5.0) && _egfr(p,30,null)
      ? { specialty:"심혈관", guideline:"ACC/AHA 2023 HF 가이드라인", priority:2, action:"추가 검토",
          drug:"MRA (Spironolactone 25 mg QD 또는 Eplerenone 25 mg QD)",
          reason:"HFrEF GDMT 2단계 — 알도스테론 차단으로 사망률 30% 감소 (RALES, EMPHASIS-HF)" } : null,

    (p, drugs) => _has(p,"심부전") && _noDrug(drugs,"SGLT2") && _egfr(p,20,null)
      ? { specialty:"심혈관", guideline:"ACC/AHA 2023 HF 가이드라인 (DAPA-HF · EMPEROR-Reduced)", priority:3, action:"추가 검토",
          drug:"SGLT2i (Dapagliflozin 10 mg QD 또는 Empagliflozin 10 mg QD)",
          reason:"HFrEF/HFpEF GDMT 3단계 — 심혈관 사망·심부전 입원 유의하게 감소" } : null,

    /* ── T2DM + CKD (ADA 2026 / KDIGO 2024) ──────────────────── */
    (p, drugs) => _has(p,"당뇨병") && _has(p,"만성신장병(CKD)") && _noDrug(drugs,"SGLT2") && _egfr(p,20,null)
      ? { specialty:"내분비/신장", guideline:"ADA 2026 / KDIGO 2024 (EMPA-KIDNEY · CREDENCE)", priority:1, action:"추가 검토",
          drug:"SGLT2i (Empagliflozin 10 mg QD 또는 Dapagliflozin 10 mg QD)",
          reason:"T2DM+CKD 1순위 — 신기능 보호(GFR 저하 25% 억제) + 심혈관 보호, eGFR ≥20에서 사용 가능" } : null,

    (p, drugs) => _has(p,"당뇨병") && _has(p,"만성신장병(CKD)") && !_egfr(p,30,null) && _noDrug(drugs,"DPP4")
      ? { specialty:"내분비/신장", guideline:"ADA 2026 / KDIGO 2024", priority:1, action:"추가 검토",
          drug:"Linagliptin 5 mg QD (신기능 조정 불필요한 DPP-4 억제제)",
          reason:"eGFR < 30: SGLT2i·Metformin 금기 → Linagliptin은 용량 조정 없이 사용 가능" } : null,

    /* ── T2DM 단독 (ADA 2026) ──────────────────────────────────── */
    (p, drugs) => _has(p,"당뇨병") && !_has(p,"만성신장병(CKD)") && !_has(p,"심부전") && _noDrug(drugs,"biguanide") && _egfr(p,30,null)
      ? { specialty:"내분비", guideline:"ADA 2026 당뇨병 표준진료", priority:1, action:"추가 검토",
          drug:"Metformin 500–1000 mg BID (eGFR ≥45 기준; 30–45면 50% 감량)",
          reason:"T2DM 1단계 기저 치료 — 체중 중립·저혈당 없음·심혈관 안전 (UKPDS)" } : null,

    (p, drugs) => _has(p,"당뇨병") && (_has(p,"관상동맥질환") || _has(p,"심방세동") || _has(p,"뇌졸중")) && _noDrug(drugs,"SGLT2","GLP1")
      ? { specialty:"내분비/심혈관", guideline:"ADA 2026 (LEADER · SUSTAIN-6 · EMPA-REG)", priority:2, action:"추가 검토",
          drug:"SGLT2i 또는 GLP-1RA (Empagliflozin 10 mg QD / Semaglutide 0.5–1 mg 주 1회)",
          reason:"T2DM + 동맥경화성 심혈관질환 — MACE(심혈관 사망·MI·뇌졸중) 유의하게 감소" } : null,

    /* ── 고혈압 + DM/CKD (ACC/AHA 2023) ──────────────────────── */
    (p, drugs) => _has(p,"고혈압") && (_has(p,"당뇨병") || _has(p,"만성신장병(CKD)")) && _noDrug(drugs,"ACEI","ARB","ARNI") && !p.pregnant && !(p.labs?.K > 5.5)
      ? { specialty:"심혈관/내분비", guideline:"ACC/AHA 2023 / 대한고혈압학회 2023", priority:1, action:"추가 검토",
          drug:"ACEi 또는 ARB (Enalapril 5 mg BID / Losartan 50 mg QD / Valsartan 80 mg QD)",
          reason:"DM·CKD 동반 고혈압 1차 권고 — RAAS 차단으로 신장·심혈관 보호" } : null,

    /* ── 심방세동 (ACC/AHA/ESC 2023) ──────────────────────────── */
    (p, drugs) => _has(p,"심방세동") && _noDrug(drugs,"anticoagulant","NOAC") && !_egfr(p,null,15)
      ? { specialty:"심혈관 (부정맥)", guideline:"ACC/AHA/ESC 2023 AF 가이드라인", priority:1, action:"추가 검토",
          drug:"NOAC (Apixaban 5 mg BID 또는 Rivaroxaban 20 mg QD; CrCl 에 따라 감량)",
          reason:"AF — CHA₂DS₂-VASc ≥2(남)/≥3(여) 시 뇌졸중 예방 항응고 필수; NOAC이 와파린 대비 안전성 우수" } : null,

    /* ── CKD (KDIGO 2024) — RAAS ──────────────────────────────── */
    (p, drugs) => _has(p,"만성신장병(CKD)") && !_has(p,"당뇨병") && _noDrug(drugs,"ACEI","ARB") && !p.pregnant && !(p.labs?.K > 5.5)
      ? { specialty:"신장내과", guideline:"KDIGO 2024 CKD 가이드라인", priority:1, action:"추가 검토",
          drug:"ACEi 또는 ARB (단백뇨 동반 시: Losartan 50–100 mg QD / Enalapril 5–20 mg QD)",
          reason:"단백뇨 동반 CKD — RAAS 차단으로 사구체내압 감소·신기능 보호 강력 권고" } : null,

    /* ── 고지혈증 / 고위험군 (ACC/AHA 2019) ───────────────────── */
    (p, drugs) => (_has(p,"고지혈증") || _has(p,"관상동맥질환") || _has(p,"뇌졸중") || (_has(p,"당뇨병") && p.age >= 40)) && _noDrug(drugs,"statin")
      ? { specialty:"심혈관 (이상지질혈증)", guideline:"ACC/AHA 2019 / 한국지질동맥경화학회 2022", priority:1, action:"추가 검토",
          drug:"중등도-고강도 Statin (Rosuvastatin 10–20 mg QD 또는 Atorvastatin 20–40 mg QD)",
          reason:"고위험군(고지혈증·CAD·DM+40세↑) — LDL 최소 50% 감소 목표, 심혈관 사건 예방" } : null,

    /* ── 통풍 ULT (ACR 2020) ──────────────────────────────────── */
    (p, drugs) => _has(p,"통풍") && _noDrug(drugs,"urate-lowering")
      ? { specialty:"류마티스 (통풍)", guideline:"ACR 2020 통풍 가이드라인", priority:1, action:"추가 검토",
          drug:"Allopurinol 100 mg QD → titration (목표 요산 < 6.0 mg/dL; CKD 동반 시 용량 감량)",
          reason:"만성 통풍 재발 방지 ULT(요산 강하 요법) — 알로퓨리놀 1차 권고, 플레어 예방 위해 Colchicine 병용 초기" } : null,

    /* ── COPD (GOLD 2024) ─────────────────────────────────────── */
    (p, drugs) => _has(p,"천식·COPD") && _noDrug(drugs,"LAMA","LABA")
      ? { specialty:"호흡기", guideline:"GOLD 2024 COPD 가이드라인", priority:1, action:"추가 검토",
          drug:"LAMA (Tiotropium 18 µg 흡입 QD) 또는 LABA/LAMA 복합제",
          reason:"COPD 안정기 GDMT — LAMA 단독 또는 LABA/LAMA 이중 기관지확장제가 1차 권고 (증상·급성악화 감소)" } : null,
  ];

  function gdmtRecommend(patient, drugs) {
    const recs = [];
    for (let i = 0; i < GDMT_POSITIVE_RULES.length; i++) {
      try {
        const r = GDMT_POSITIVE_RULES[i](patient, drugs);
        if (r) {
          const evKey = _GDMT_RULE_EVKEY[i];
          const ev = evKey ? GDMT_EVIDENCE_DB[evKey] : null;
          recs.push(ev ? { ...r, clinical_evidence: ev } : r);
        }
      } catch {}
    }
    return recs.sort((a, b) => a.priority - b.priority);
  }

  /* ===== 대체약 추천 ===== */
  function recommendAlternative(drug, patient) {
    const has = d => patient.baseDiseases?.includes(d);
    const age = patient.age || 0;

    if (drug.drugClass === "NSAID" || drug.drugClass === "COX2") {
      const first = { name: "Acetaminophen", dose: "500mg 1T tid prn", why: "신·위장·심혈관 안전성 우수, 1차 권장 진통제" };
      let second;
      if (has("전립선비대") || has("녹내장") || age >= 65) {
        second = { name: "Tramadol", dose: "50mg 1T bid prn", why: "비NSAID 옵션, 경중등도 통증" };
      } else {
        second = { name: "Celecoxib (저용량)", dose: "100mg 1T qd", why: "GI 부담 감소 COX-2 선택적, 단기 사용 시" };
      }
      return { first, second };
    }

    if (drug.key === "metformin") {
      return {
        first:  { name: "Empagliflozin", dose: "10mg 1T qd",  why: "CKD/심부전에서 신·심혈관 보호 효과" },
        second: { name: "Linagliptin",   dose: "5mg 1T qd",   why: "신기능 조정 불필요한 DPP-4 억제제" },
      };
    }

    if (drug.drugClass === "fluoroquinolone") {
      return {
        first:  { name: "Amoxicillin/Clavulanate", dose: "625mg 1T bid × 7일", why: "QT 영향 없음, 광범위 β-lactam" },
        second: { name: "Cefixime",                 dose: "100mg 1T bid × 7일", why: "경구 3세대 cephalosporin, 안전성 양호" },
      };
    }

    if (drug.drugClass === "macrolide") {
      return {
        first:  { name: "Doxycycline", dose: "100mg 1T bid × 7일", why: "QT 연장 없음, 유사 스펙트럼" },
        second: { name: "Amoxicillin", dose: "500mg 1T tid × 7일", why: "1차 경험 항생제, QT 안전" },
      };
    }

    if (drug.drugClass === "BZD") {
      return {
        first:  { name: "Melatonin",         dose: "2mg qhs",   why: "고령 불면에 낙상 위험 없이 사용" },
        second: { name: "Trazodone (저용량)", dose: "25mg qhs",  why: "의존성 낮음, 고령에서 선호" },
      };
    }

    if (drug.drugClass === "TCA") {
      return {
        first:  { name: "Sertraline",  dose: "50mg 1T qd", why: "SSRI — 항콜린성 없음" },
        second: { name: "Duloxetine",  dose: "30mg 1T qd", why: "신경병증성 통증 동반 시 유리" },
      };
    }

    if (drug.drugClass === "antihistamine-1gen") {
      return {
        first:  { name: "Cetirizine",  dose: "10mg 1T qd", why: "2세대 — 인지·낙상 위험 낮음" },
        second: { name: "Loratadine",  dose: "10mg 1T qd", why: "2세대 — 졸림 거의 없음" },
      };
    }

    if (drug.key === "propranolol" && has("천식·COPD")) {
      return {
        first:  { name: "Bisoprolol (선택적 β1)", dose: "2.5mg 1T qd", why: "기관지 영향 적은 심장선택성" },
        second: { name: "Diltiazem",              dose: "90mg 1T bid",  why: "비-β 옵션, 심박 조절" },
      };
    }

    if ((drug.drugClass === "ACEI" || drug.drugClass === "ARB") && patient.pregnant) {
      return {
        first:  { name: "Labetalol",  dose: "100mg 1T bid", why: "임신 고혈압 1차 권장" },
        second: { name: "Methyldopa", dose: "250mg 1T bid", why: "임신 안전성 장기 데이터" },
      };
    }

    return null;
  }

  /* ===== analyze() — 메인 엔트리 ===== */
  function analyze(patient, rxText) {
    const _sevOrd = { critical: 4, high: 3, warn: 2, ok: 1 };
    const lines = (rxText || "").split("\n").map(s => s.trim()).filter(Boolean);
    const drugs = lines.map(parseDrug).filter(Boolean);

    // 개별 약물 규칙 체크
    const items = drugs.map(d => {
      const findings = [];
      for (const rule of RULES) {
        try {
          const f = rule(patient, d, drugs);
          if (f) findings.push(enrichFinding(f));
        } catch {}
      }
      const sev = findings.length
        ? findings.reduce((a, b) => _sevOrd[a.sev] >= _sevOrd[b.sev] ? a : b).sev
        : "ok";
      return { drug: d, findings, sev };
    });

    const counts = { critical: 0, high: 0, warn: 0, ok: 0 };
    items.forEach(x => counts[x.sev]++);

    // DDI 쌍별 상호작용 전수 체크
    const ddi = checkDDI(drugs);

    // 종합 위험도: 개별 약물 최고 등급 vs DDI 최고 등급 중 높은 것
    const allSevs = [
      ...items.map(x => x.sev),
      ...ddi.map(d => d.sev),
    ];
    const overallRisk = allSevs.length
      ? allSevs.reduce((a, b) => _sevOrd[a] >= _sevOrd[b] ? a : b, "ok")
      : "ok";

    const recommendations = [];
    items.forEach(x => {
      if (x.sev === "critical" || x.sev === "high") {
        const rec = recommendAlternative(x.drug, patient);
        if (rec) {
          const topReason = x.findings.find(f => f.sev === x.sev)?.reason || "위험";
          recommendations.push({
            target: `${x.drug.name} ${x.drug.strength}`.trim(),
            reason: topReason,
            first:  rec.first,
            second: rec.second,
          });
        }
      }
    });

    const gdmt = gdmtRecommend(patient, drugs);
    return { drugs: items, counts, recommendations, gdmt, ddi, overallRisk };
  }

  async function patchNote(dbId, noteText) {
    const p = _cache.find(x => x._dbId === dbId);
    if (!p) return;
    p.note = noteText;
    await _patchPatient(dbId, { clinical_notes: _buildClinicalNotes(p, "waiting") });
  }

  async function patchLabs(dbId, labs, labNotes) {
    const p = _cache.find(x => x._dbId === dbId);
    if (!p) return;
    p.labs    = { ...(p.labs || {}), ...labs };
    p.labNotes = labNotes ?? p.labNotes ?? "";
    await _patchPatient(dbId, {
      lab_values:    _buildLabValues(p.labs),
      clinical_notes: _buildClinicalNotes(p, "waiting"),
    });
  }

  async function patchPrescription(dbId, prescription) {
    const p = _cache.find(x => x._dbId === dbId);
    if (!p) return;
    p.prescription = prescription;
    await _patchPatient(dbId, {
      current_medications: { history: p.history || "", prescription },
      clinical_notes: _buildClinicalNotes(p, "waiting"),
    });
  }

  global.RxAssist = {
    BASE_DISEASES_15, loadQueue, saveQueue, patchNote, patchLabs, patchPrescription, subscribe, analyze,
  };
})(window);
