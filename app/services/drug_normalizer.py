"""약물명 정규화 모듈.

LocalDrugMasterProvider 가 기본 구현이며,
추후 HIRA API / 식약처 API provider로 교체 가능한 ABC 인터페이스를 제공한다.
"""
import re
from abc import ABC, abstractmethod
from app.schemas.history import NormalizedDrug


# ──────────────────────────────────────────────────────────────────────────────
# 로컬 약물 마스터 DB
# key: 영문 성분명 소문자 (검색 기준값)
# ──────────────────────────────────────────────────────────────────────────────
DRUG_MASTER_DB: dict[str, dict] = {
    # ── 당뇨 ──────────────────────────────────────────────────────────────────
    "metformin": {
        "normalized_name": "메트포르민", "ingredient_code": "A10BA02",
        "ingredient_names": ["metformin", "메트포르민", "메트포민"],
        "drug_class": "biguanide", "combination": False, "components": [],
        "product_names": ["글루코파지", "다이아벡스", "메트포민", "메트포르민정"],
        "aliases": ["메트포르민염산염", "metformin hcl", "metformin hydrochloride"],
    },
    "empagliflozin": {
        "normalized_name": "엠파글리플로진", "ingredient_code": "A10BK03",
        "ingredient_names": ["empagliflozin", "엠파글리플로진"],
        "drug_class": "SGLT2", "combination": False, "components": [],
        "product_names": ["자디앙", "jardiance"], "aliases": [],
    },
    "dapagliflozin": {
        "normalized_name": "다파글리플로진", "ingredient_code": "A10BK01",
        "ingredient_names": ["dapagliflozin", "다파글리플로진"],
        "drug_class": "SGLT2", "combination": False, "components": [],
        "product_names": ["포시가", "forxiga"], "aliases": [],
    },
    "canagliflozin": {
        "normalized_name": "카나글리플로진", "ingredient_code": "A10BK02",
        "ingredient_names": ["canagliflozin", "카나글리플로진"],
        "drug_class": "SGLT2", "combination": False, "components": [],
        "product_names": ["인보카나", "invokana"], "aliases": [],
    },
    "sitagliptin": {
        "normalized_name": "시타글립틴", "ingredient_code": "A10BH01",
        "ingredient_names": ["sitagliptin", "시타글립틴"],
        "drug_class": "DPP4", "combination": False, "components": [],
        "product_names": ["자누비아", "januvia"], "aliases": [],
    },
    "linagliptin": {
        "normalized_name": "리나글립틴", "ingredient_code": "A10BH05",
        "ingredient_names": ["linagliptin", "리나글립틴"],
        "drug_class": "DPP4", "combination": False, "components": [],
        "product_names": ["트라젠타", "trajenta"], "aliases": [],
    },
    "vildagliptin": {
        "normalized_name": "빌다글립틴", "ingredient_code": "A10BH02",
        "ingredient_names": ["vildagliptin", "빌다글립틴"],
        "drug_class": "DPP4", "combination": False, "components": [],
        "product_names": ["가브스", "galvus"], "aliases": [],
    },
    "glimepiride": {
        "normalized_name": "글리메피리드", "ingredient_code": "A10BB12",
        "ingredient_names": ["glimepiride", "글리메피리드"],
        "drug_class": "sulfonylurea", "combination": False, "components": [],
        "product_names": ["아마릴", "amaryl"], "aliases": [],
    },
    "gliclazide": {
        "normalized_name": "글리클라지드", "ingredient_code": "A10BB09",
        "ingredient_names": ["gliclazide", "글리클라지드"],
        "drug_class": "sulfonylurea", "combination": False, "components": [],
        "product_names": ["다이아미크롱", "diamicron"], "aliases": [],
    },
    "liraglutide": {
        "normalized_name": "리라글루티드", "ingredient_code": "A10BJ02",
        "ingredient_names": ["liraglutide", "리라글루티드"],
        "drug_class": "GLP1", "combination": False, "components": [],
        "product_names": ["빅토자", "victoza"], "aliases": [],
    },
    "semaglutide": {
        "normalized_name": "세마글루티드", "ingredient_code": "A10BJ06",
        "ingredient_names": ["semaglutide", "세마글루티드"],
        "drug_class": "GLP1", "combination": False, "components": [],
        "product_names": ["오젬픽", "ozempic", "위고비", "wegovy"], "aliases": [],
    },
    "dulaglutide": {
        "normalized_name": "둘라글루티드", "ingredient_code": "A10BJ05",
        "ingredient_names": ["dulaglutide", "둘라글루티드"],
        "drug_class": "GLP1", "combination": False, "components": [],
        "product_names": ["트루리시티", "trulicity"], "aliases": [],
    },
    # ── 심혈관 ────────────────────────────────────────────────────────────────
    "amlodipine": {
        "normalized_name": "암로디핀", "ingredient_code": "C08CA01",
        "ingredient_names": ["amlodipine", "암로디핀"],
        "drug_class": "CCB", "combination": False, "components": [],
        "product_names": ["노바스크", "norvasc", "암로핀"], "aliases": [],
    },
    "losartan": {
        "normalized_name": "로사르탄", "ingredient_code": "C09CA01",
        "ingredient_names": ["losartan", "로사르탄"],
        "drug_class": "ARB", "combination": False, "components": [],
        "product_names": ["코자", "cozaar", "로자탄"], "aliases": [],
    },
    "valsartan": {
        "normalized_name": "발사르탄", "ingredient_code": "C09CA03",
        "ingredient_names": ["valsartan", "발사르탄"],
        "drug_class": "ARB", "combination": False, "components": [],
        "product_names": ["디오반", "diovan"], "aliases": [],
    },
    "olmesartan": {
        "normalized_name": "올메사르탄", "ingredient_code": "C09CA08",
        "ingredient_names": ["olmesartan", "올메사르탄"],
        "drug_class": "ARB", "combination": False, "components": [],
        "product_names": ["올메텍", "olmetec", "베니카"], "aliases": [],
    },
    "enalapril": {
        "normalized_name": "에날라프릴", "ingredient_code": "C09AA02",
        "ingredient_names": ["enalapril", "에날라프릴"],
        "drug_class": "ACEI", "combination": False, "components": [],
        "product_names": ["레니텍", "renitec"], "aliases": ["에나프릴"],
    },
    "lisinopril": {
        "normalized_name": "리시노프릴", "ingredient_code": "C09AA03",
        "ingredient_names": ["lisinopril", "리시노프릴"],
        "drug_class": "ACEI", "combination": False, "components": [],
        "product_names": ["제스트릴", "zestril", "프린이빌"], "aliases": [],
    },
    "bisoprolol": {
        "normalized_name": "비소프롤롤", "ingredient_code": "C07AB07",
        "ingredient_names": ["bisoprolol", "비소프롤롤"],
        "drug_class": "betablocker-selective", "combination": False, "components": [],
        "product_names": ["콩코르", "concor"], "aliases": ["비소프로롤"],
    },
    "carvedilol": {
        "normalized_name": "카르베딜롤", "ingredient_code": "C07AG02",
        "ingredient_names": ["carvedilol", "카르베딜롤"],
        "drug_class": "betablocker", "combination": False, "components": [],
        "product_names": ["딜라트렌드", "dilatrend", "카베딜롤"], "aliases": [],
    },
    "metoprolol": {
        "normalized_name": "메토프롤롤", "ingredient_code": "C07AB02",
        "ingredient_names": ["metoprolol", "메토프롤롤"],
        "drug_class": "betablocker-selective", "combination": False, "components": [],
        "product_names": ["베탈록", "betaloc"], "aliases": [],
    },
    "propranolol": {
        "normalized_name": "프로프라놀롤", "ingredient_code": "C07AA05",
        "ingredient_names": ["propranolol", "프로프라놀롤"],
        "drug_class": "betablocker", "combination": False, "components": [],
        "product_names": ["인데랄", "inderal"], "aliases": [],
    },
    "spironolactone": {
        "normalized_name": "스피로노락톤", "ingredient_code": "C03DA01",
        "ingredient_names": ["spironolactone", "스피로노락톤"],
        "drug_class": "K-sparing", "combination": False, "components": [],
        "product_names": ["알닥톤", "aldactone"], "aliases": [],
    },
    "eplerenone": {
        "normalized_name": "에플레레논", "ingredient_code": "C03DA04",
        "ingredient_names": ["eplerenone", "에플레레논"],
        "drug_class": "K-sparing", "combination": False, "components": [],
        "product_names": ["인스프라", "inspra"], "aliases": [],
    },
    "hydrochlorothiazide": {
        "normalized_name": "히드로클로로티아지드", "ingredient_code": "C03AA03",
        "ingredient_names": ["hydrochlorothiazide", "히드로클로로티아지드", "hctz"],
        "drug_class": "thiazide", "combination": False, "components": [],
        "product_names": ["다이크로짇", "다이크로진"], "aliases": ["HCTZ"],
    },
    "sacubitril_valsartan": {
        "normalized_name": "사쿠비트릴/발사르탄", "ingredient_code": "C09DX04",
        "ingredient_names": ["sacubitril", "사쿠비트릴", "valsartan", "발사르탄"],
        "drug_class": "ARNI", "combination": True,
        "components": ["sacubitril", "valsartan"],
        "product_names": ["엔트레스토", "entresto"], "aliases": [],
    },
    # ── 지질 ──────────────────────────────────────────────────────────────────
    "rosuvastatin": {
        "normalized_name": "로수바스타틴", "ingredient_code": "C10AA07",
        "ingredient_names": ["rosuvastatin", "로수바스타틴"],
        "drug_class": "statin", "combination": False, "components": [],
        "product_names": ["크레스토", "crestor", "수바스타틴"], "aliases": [],
    },
    "atorvastatin": {
        "normalized_name": "아토르바스타틴", "ingredient_code": "C10AA05",
        "ingredient_names": ["atorvastatin", "아토르바스타틴"],
        "drug_class": "statin", "combination": False, "components": [],
        "product_names": ["리피토", "lipitor"], "aliases": [],
    },
    "simvastatin": {
        "normalized_name": "심바스타틴", "ingredient_code": "C10AA01",
        "ingredient_names": ["simvastatin", "심바스타틴"],
        "drug_class": "statin", "combination": False, "components": [],
        "product_names": ["조코", "zocor"], "aliases": [],
    },
    "pravastatin": {
        "normalized_name": "프라바스타틴", "ingredient_code": "C10AA03",
        "ingredient_names": ["pravastatin", "프라바스타틴"],
        "drug_class": "statin", "combination": False, "components": [],
        "product_names": ["메바로친", "mevalotin"], "aliases": [],
    },
    "pitavastatin": {
        "normalized_name": "피타바스타틴", "ingredient_code": "C10AA08",
        "ingredient_names": ["pitavastatin", "피타바스타틴"],
        "drug_class": "statin", "combination": False, "components": [],
        "product_names": ["리바로", "livalo"], "aliases": [],
    },
    # ── 항응고 ────────────────────────────────────────────────────────────────
    "warfarin": {
        "normalized_name": "와파린", "ingredient_code": "B01AA03",
        "ingredient_names": ["warfarin", "와파린"],
        "drug_class": "anticoagulant", "combination": False, "components": [],
        "product_names": ["쿠마딘", "coumadin", "와파린정"], "aliases": [],
    },
    "apixaban": {
        "normalized_name": "아픽사반", "ingredient_code": "B01AF02",
        "ingredient_names": ["apixaban", "아픽사반"],
        "drug_class": "NOAC", "combination": False, "components": [],
        "product_names": ["엘리퀴스", "eliquis"], "aliases": [],
    },
    "rivaroxaban": {
        "normalized_name": "리바록사반", "ingredient_code": "B01AF01",
        "ingredient_names": ["rivaroxaban", "리바록사반"],
        "drug_class": "NOAC", "combination": False, "components": [],
        "product_names": ["자렐토", "xarelto"], "aliases": [],
    },
    "dabigatran": {
        "normalized_name": "다비가트란", "ingredient_code": "B01AE07",
        "ingredient_names": ["dabigatran", "다비가트란"],
        "drug_class": "NOAC", "combination": False, "components": [],
        "product_names": ["프라닥사", "pradaxa"], "aliases": [],
    },
    "edoxaban": {
        "normalized_name": "에독사반", "ingredient_code": "B01AF03",
        "ingredient_names": ["edoxaban", "에독사반"],
        "drug_class": "NOAC", "combination": False, "components": [],
        "product_names": ["릭시아나", "lixiana"], "aliases": [],
    },
    "aspirin": {
        "normalized_name": "아스피린", "ingredient_code": "B01AC06",
        "ingredient_names": ["aspirin", "아스피린", "acetylsalicylic acid"],
        "drug_class": "antiplatelet", "combination": False, "components": [],
        "product_names": ["아스피린프로텍트", "아스트릭스", "바이아스피린"], "aliases": ["ASA"],
    },
    # ── 소화기 ────────────────────────────────────────────────────────────────
    "omeprazole": {
        "normalized_name": "오메프라졸", "ingredient_code": "A02BC01",
        "ingredient_names": ["omeprazole", "오메프라졸"],
        "drug_class": "PPI", "combination": False, "components": [],
        "product_names": ["오메드", "prilosec", "로섹"], "aliases": [],
    },
    "esomeprazole": {
        "normalized_name": "에소메프라졸", "ingredient_code": "A02BC05",
        "ingredient_names": ["esomeprazole", "에소메프라졸"],
        "drug_class": "PPI", "combination": False, "components": [],
        "product_names": ["넥시움", "nexium"], "aliases": [],
    },
    "pantoprazole": {
        "normalized_name": "판토프라졸", "ingredient_code": "A02BC02",
        "ingredient_names": ["pantoprazole", "판토프라졸"],
        "drug_class": "PPI", "combination": False, "components": [],
        "product_names": ["판토록", "pantoloc", "울트롭"], "aliases": [],
    },
    "rabeprazole": {
        "normalized_name": "라베프라졸", "ingredient_code": "A02BC04",
        "ingredient_names": ["rabeprazole", "라베프라졸"],
        "drug_class": "PPI", "combination": False, "components": [],
        "product_names": ["파리에트", "pariet"], "aliases": [],
    },
    # ── NSAIDs / 진통제 ───────────────────────────────────────────────────────
    "celecoxib": {
        "normalized_name": "세레콕시브", "ingredient_code": "M01AH01",
        "ingredient_names": ["celecoxib", "세레콕시브", "셀레콕시브"],
        "drug_class": "COX2", "combination": False, "components": [],
        "product_names": ["쎄레브렉스", "celebrex"], "aliases": [],
    },
    "ibuprofen": {
        "normalized_name": "이부프로펜", "ingredient_code": "M01AE01",
        "ingredient_names": ["ibuprofen", "이부프로펜"],
        "drug_class": "NSAID", "combination": False, "components": [],
        "product_names": ["부루펜", "애드빌", "advil"], "aliases": [],
    },
    "naproxen": {
        "normalized_name": "나프록센", "ingredient_code": "M01AE02",
        "ingredient_names": ["naproxen", "나프록센"],
        "drug_class": "NSAID", "combination": False, "components": [],
        "product_names": ["낙센", "naprosyn", "알리브"], "aliases": [],
    },
    "diclofenac": {
        "normalized_name": "디클로페낙", "ingredient_code": "M01AB05",
        "ingredient_names": ["diclofenac", "디클로페낙"],
        "drug_class": "NSAID", "combination": False, "components": [],
        "product_names": ["볼타렌", "voltaren", "디크로"], "aliases": [],
    },
    "aceclofenac": {
        "normalized_name": "아세클로페낙", "ingredient_code": "M01AB16",
        "ingredient_names": ["aceclofenac", "아세클로페낙"],
        "drug_class": "NSAID", "combination": False, "components": [],
        "product_names": ["에어탈", "airtal", "아세페낙"], "aliases": [],
    },
    "acetaminophen": {
        "normalized_name": "아세트아미노펜", "ingredient_code": "N02BE01",
        "ingredient_names": ["acetaminophen", "아세트아미노펜", "paracetamol", "파라세타몰"],
        "drug_class": "analgesic", "combination": False, "components": [],
        "product_names": ["타이레놀", "tylenol", "게보린", "판피린"], "aliases": ["AAP"],
    },
    "tramadol": {
        "normalized_name": "트라마돌", "ingredient_code": "N02AX02",
        "ingredient_names": ["tramadol", "트라마돌"],
        "drug_class": "opioid", "combination": False, "components": [],
        "product_names": ["트라마딘", "ultram", "트리돌"], "aliases": [],
    },
    # ── 항생제 ────────────────────────────────────────────────────────────────
    "amoxicillin": {
        "normalized_name": "아목시실린", "ingredient_code": "J01CA04",
        "ingredient_names": ["amoxicillin", "아목시실린"],
        "drug_class": "penicillin", "combination": False, "components": [],
        "product_names": ["아모신", "amoxil", "아모크라"], "aliases": [],
    },
    "ciprofloxacin": {
        "normalized_name": "시프로플록사신", "ingredient_code": "J01MA02",
        "ingredient_names": ["ciprofloxacin", "시프로플록사신"],
        "drug_class": "fluoroquinolone", "combination": False, "components": [],
        "product_names": ["시프록", "ciprobay", "씨프로"], "aliases": [],
    },
    "levofloxacin": {
        "normalized_name": "레보플록사신", "ingredient_code": "J01MA12",
        "ingredient_names": ["levofloxacin", "레보플록사신"],
        "drug_class": "fluoroquinolone", "combination": False, "components": [],
        "product_names": ["크라비트", "cravit", "레바퀸"], "aliases": [],
    },
    "azithromycin": {
        "normalized_name": "아지트로마이신", "ingredient_code": "J01FA10",
        "ingredient_names": ["azithromycin", "아지트로마이신"],
        "drug_class": "macrolide", "combination": False, "components": [],
        "product_names": ["지스로맥스", "zithromax"], "aliases": [],
    },
    "clarithromycin": {
        "normalized_name": "클래리트로마이신", "ingredient_code": "J01FA09",
        "ingredient_names": ["clarithromycin", "클래리트로마이신", "클라리트로마이신"],
        "drug_class": "macrolide", "combination": False, "components": [],
        "product_names": ["클래리시드", "klacid"], "aliases": [],
    },
    # ── 정신과 ────────────────────────────────────────────────────────────────
    "risperidone": {
        "normalized_name": "리스페리돈", "ingredient_code": "N05AX08",
        "ingredient_names": ["risperidone", "리스페리돈"],
        "drug_class": "antipsychotic-SGA", "combination": False, "components": [],
        "product_names": ["리스페달", "risperdal", "리스페리돈정"],
        "aliases": ["리스페달", "리스페리도"],
    },
    "aripiprazole": {
        "normalized_name": "아리피프라졸", "ingredient_code": "N05AX12",
        "ingredient_names": ["aripiprazole", "아리피프라졸"],
        "drug_class": "antipsychotic-SGA", "combination": False, "components": [],
        "product_names": ["아빌리파이", "abilify"],
        "aliases": ["아리피프라졸정", "아리피"],
    },
    "quetiapine": {
        "normalized_name": "쿠에티아핀", "ingredient_code": "N05AH04",
        "ingredient_names": ["quetiapine", "쿠에티아핀"],
        "drug_class": "antipsychotic-SGA", "combination": False, "components": [],
        "product_names": ["세로켈", "seroquel", "쿠에타핀"],
        "aliases": ["쿼에티아핀"],
    },
    "olanzapine": {
        "normalized_name": "올란자핀", "ingredient_code": "N05AH03",
        "ingredient_names": ["olanzapine", "올란자핀"],
        "drug_class": "antipsychotic-SGA", "combination": False, "components": [],
        "product_names": ["자이프렉사", "zyprexa"], "aliases": [],
    },
    "clozapine": {
        "normalized_name": "클로자핀", "ingredient_code": "N05AH02",
        "ingredient_names": ["clozapine", "클로자핀"],
        "drug_class": "antipsychotic-SGA", "combination": False, "components": [],
        "product_names": ["클로자릴", "clozaril"], "aliases": [],
    },
    "haloperidol": {
        "normalized_name": "할로페리돌", "ingredient_code": "N05AD01",
        "ingredient_names": ["haloperidol", "할로페리돌"],
        "drug_class": "antipsychotic-FGA", "combination": False, "components": [],
        "product_names": ["할돌", "haldol"], "aliases": [],
    },
    "sertraline": {
        "normalized_name": "서트랄린", "ingredient_code": "N06AB06",
        "ingredient_names": ["sertraline", "서트랄린"],
        "drug_class": "SSRI", "combination": False, "components": [],
        "product_names": ["졸로푸트", "zoloft"], "aliases": ["설트랄린"],
    },
    "escitalopram": {
        "normalized_name": "에스시탈로프람", "ingredient_code": "N06AB10",
        "ingredient_names": ["escitalopram", "에스시탈로프람"],
        "drug_class": "SSRI", "combination": False, "components": [],
        "product_names": ["렉사프로", "lexapro", "씨프라밀"], "aliases": ["에스시탈"],
    },
    "fluoxetine": {
        "normalized_name": "플루옥세틴", "ingredient_code": "N06AB03",
        "ingredient_names": ["fluoxetine", "플루옥세틴"],
        "drug_class": "SSRI", "combination": False, "components": [],
        "product_names": ["프로작", "prozac", "박스민"], "aliases": [],
    },
    "paroxetine": {
        "normalized_name": "파록세틴", "ingredient_code": "N06AB05",
        "ingredient_names": ["paroxetine", "파록세틴"],
        "drug_class": "SSRI", "combination": False, "components": [],
        "product_names": ["팍실", "paxil", "세로자트"], "aliases": [],
    },
    "venlafaxine": {
        "normalized_name": "벤라팍신", "ingredient_code": "N06AX16",
        "ingredient_names": ["venlafaxine", "벤라팍신"],
        "drug_class": "SNRI", "combination": False, "components": [],
        "product_names": ["이팩사", "effexor"], "aliases": [],
    },
    "duloxetine": {
        "normalized_name": "둘록세틴", "ingredient_code": "N06AX21",
        "ingredient_names": ["duloxetine", "둘록세틴"],
        "drug_class": "SNRI", "combination": False, "components": [],
        "product_names": ["심발타", "cymbalta"], "aliases": [],
    },
    "trazodone": {
        "normalized_name": "트라조돈", "ingredient_code": "N06AX05",
        "ingredient_names": ["trazodone", "트라조돈"],
        "drug_class": "SARI", "combination": False, "components": [],
        "product_names": ["데시렐", "desyrel", "트리티코"],
        "aliases": ["트라조돈정"],
    },
    "mirtazapine": {
        "normalized_name": "미르타자핀", "ingredient_code": "N06AX11",
        "ingredient_names": ["mirtazapine", "미르타자핀"],
        "drug_class": "NaSSA", "combination": False, "components": [],
        "product_names": ["레메론", "remeron"], "aliases": [],
    },
    "amitriptyline": {
        "normalized_name": "아미트립틸린", "ingredient_code": "N06AA09",
        "ingredient_names": ["amitriptyline", "아미트립틸린"],
        "drug_class": "TCA", "combination": False, "components": [],
        "product_names": ["에트라빌", "elavil"], "aliases": [],
    },
    "nortriptyline": {
        "normalized_name": "노르트립틸린", "ingredient_code": "N06AA10",
        "ingredient_names": ["nortriptyline", "노르트립틸린"],
        "drug_class": "TCA", "combination": False, "components": [],
        "product_names": ["파멜로", "pamelor"], "aliases": [],
    },
    "alprazolam": {
        "normalized_name": "알프라졸람", "ingredient_code": "N05BA12",
        "ingredient_names": ["alprazolam", "알프라졸람"],
        "drug_class": "BZD", "combination": False, "components": [],
        "product_names": ["자낙스", "xanax", "알프람"], "aliases": [],
    },
    "lorazepam": {
        "normalized_name": "로라제팜", "ingredient_code": "N05BA06",
        "ingredient_names": ["lorazepam", "로라제팜"],
        "drug_class": "BZD", "combination": False, "components": [],
        "product_names": ["아티반", "ativan"], "aliases": [],
    },
    "diazepam": {
        "normalized_name": "디아제팜", "ingredient_code": "N05BA01",
        "ingredient_names": ["diazepam", "디아제팜"],
        "drug_class": "BZD", "combination": False, "components": [],
        "product_names": ["발리움", "valium"], "aliases": [],
    },
    "clonazepam": {
        "normalized_name": "클로나제팜", "ingredient_code": "N03AE01",
        "ingredient_names": ["clonazepam", "클로나제팜"],
        "drug_class": "BZD", "combination": False, "components": [],
        "product_names": ["리보트릴", "rivotril", "클로나핀"], "aliases": [],
    },
    "zolpidem": {
        "normalized_name": "졸피뎀", "ingredient_code": "N05CF02",
        "ingredient_names": ["zolpidem", "졸피뎀"],
        "drug_class": "Z-drug", "combination": False, "components": [],
        "product_names": ["스틸녹스", "stilnox", "졸피뎀정"],
        "aliases": ["졸피뎀주석산염"],
    },
    "melatonin": {
        "normalized_name": "멜라토닌", "ingredient_code": "N05CH01",
        "ingredient_names": ["melatonin", "멜라토닌"],
        "drug_class": "melatonin-agonist", "combination": False, "components": [],
        "product_names": ["써커딘", "circadin"], "aliases": [],
    },
    "lithium": {
        "normalized_name": "리튬", "ingredient_code": "N05AN01",
        "ingredient_names": ["lithium", "리튬", "lithium carbonate"],
        "drug_class": "mood-stabilizer", "combination": False, "components": [],
        "product_names": ["리토나이트", "eskalith", "리튬카보네이트"],
        "aliases": ["탄산리튬", "lithium carbonate"],
    },
    "valproate": {
        "normalized_name": "발프로에이트", "ingredient_code": "N03AG01",
        "ingredient_names": ["valproate", "발프로에이트", "valproic acid", "발프로산"],
        "drug_class": "mood-stabilizer", "combination": False, "components": [],
        "product_names": ["데파코트", "depakote", "오르필", "발프론"],
        "aliases": ["발프로산나트륨", "sodium valproate"],
    },
    "lamotrigine": {
        "normalized_name": "라모트리진", "ingredient_code": "N03AX09",
        "ingredient_names": ["lamotrigine", "라모트리진"],
        "drug_class": "mood-stabilizer", "combination": False, "components": [],
        "product_names": ["라믹탈", "lamictal"], "aliases": [],
    },
    # ── 류마티스 / 항염 ──────────────────────────────────────────────────────
    "methotrexate": {
        "normalized_name": "메토트렉세이트", "ingredient_code": "L04AX03",
        "ingredient_names": ["methotrexate", "메토트렉세이트"],
        "drug_class": "DMARD", "combination": False, "components": [],
        "product_names": ["메토젝트", "mtx주", "메토트렉세이트정"],
        "aliases": ["MTX"],
    },
    "folic_acid": {
        "normalized_name": "엽산", "ingredient_code": "B03BB01",
        "ingredient_names": ["folic acid", "엽산", "folate"],
        "drug_class": "vitamin", "combination": False, "components": [],
        "product_names": ["엽산정", "폴린산"], "aliases": ["폴산"],
    },
    "prednisolone": {
        "normalized_name": "프레드니솔론", "ingredient_code": "H02AB06",
        "ingredient_names": ["prednisolone", "프레드니솔론"],
        "drug_class": "steroid", "combination": False, "components": [],
        "product_names": ["소론도", "예니솔론", "프레드니솔론정"], "aliases": [],
    },
    "methylprednisolone": {
        "normalized_name": "메틸프레드니솔론", "ingredient_code": "H02AB04",
        "ingredient_names": ["methylprednisolone", "메틸프레드니솔론"],
        "drug_class": "steroid", "combination": False, "components": [],
        "product_names": ["메드롤", "solu-medrol", "솔루메드롤"], "aliases": [],
    },
    # ── 통풍 ──────────────────────────────────────────────────────────────────
    "allopurinol": {
        "normalized_name": "알로퓨리놀", "ingredient_code": "M04AA01",
        "ingredient_names": ["allopurinol", "알로퓨리놀"],
        "drug_class": "urate-lowering", "combination": False, "components": [],
        "product_names": ["자이로릭", "zyloprim", "알로퓨린"], "aliases": [],
    },
    "febuxostat": {
        "normalized_name": "페북소스타트", "ingredient_code": "M04AA03",
        "ingredient_names": ["febuxostat", "페북소스타트"],
        "drug_class": "urate-lowering", "combination": False, "components": [],
        "product_names": ["울로릭", "uloric", "페북소스타트정"], "aliases": [],
    },
    # ── 호흡기 ────────────────────────────────────────────────────────────────
    "tiotropium": {
        "normalized_name": "티오트로피움", "ingredient_code": "R03BB04",
        "ingredient_names": ["tiotropium", "티오트로피움"],
        "drug_class": "LAMA", "combination": False, "components": [],
        "product_names": ["스피리바", "spiriva"], "aliases": [],
    },
    "salbutamol": {
        "normalized_name": "살부타몰", "ingredient_code": "R03AC02",
        "ingredient_names": ["salbutamol", "살부타몰", "albuterol", "알부테롤"],
        "drug_class": "SABA", "combination": False, "components": [],
        "product_names": ["벤토린", "ventolin", "살부탄"], "aliases": [],
    },
    # ── 항히스타민 ────────────────────────────────────────────────────────────
    "cetirizine": {
        "normalized_name": "세티리진", "ingredient_code": "R06AE07",
        "ingredient_names": ["cetirizine", "세티리진"],
        "drug_class": "antihistamine-2gen", "combination": False, "components": [],
        "product_names": ["지르텍", "zyrtec", "씨잘"], "aliases": [],
    },
    "chlorpheniramine": {
        "normalized_name": "클로르페니라민", "ingredient_code": "R06AB02",
        "ingredient_names": ["chlorpheniramine", "클로르페니라민"],
        "drug_class": "antihistamine-1gen", "combination": False, "components": [],
        "product_names": ["페니라민", "알러민"], "aliases": [],
    },
    # ── 근이완제 ──────────────────────────────────────────────────────────────
    "eperisone": {
        "normalized_name": "에페리손", "ingredient_code": "M03BX09",
        "ingredient_names": ["eperisone", "에페리손"],
        "drug_class": "muscle-relaxant", "combination": False, "components": [],
        "product_names": ["미오날", "myonal"], "aliases": [],
    },
    # ── 복합제 예시 ───────────────────────────────────────────────────────────
    "metformin_sitagliptin": {
        "normalized_name": "메트포르민/시타글립틴", "ingredient_code": None,
        "ingredient_names": ["metformin", "sitagliptin", "메트포르민", "시타글립틴"],
        "drug_class": "biguanide+DPP4", "combination": True,
        "components": ["metformin", "sitagliptin"],
        "product_names": ["자누메트", "janumet"], "aliases": [],
    },
    "metformin_empagliflozin": {
        "normalized_name": "메트포르민/엠파글리플로진", "ingredient_code": None,
        "ingredient_names": ["metformin", "empagliflozin", "메트포르민", "엠파글리플로진"],
        "drug_class": "biguanide+SGLT2", "combination": True,
        "components": ["metformin", "empagliflozin"],
        "product_names": ["자디앙듀오", "synjardy"], "aliases": [],
    },
    "amlodipine_losartan": {
        "normalized_name": "암로디핀/로사르탄", "ingredient_code": None,
        "ingredient_names": ["amlodipine", "losartan", "암로디핀", "로사르탄"],
        "drug_class": "CCB+ARB", "combination": True,
        "components": ["amlodipine", "losartan"],
        "product_names": ["로바티"], "aliases": [],
    },
}

# 검색 인덱스 사전 (정규화된 소문자 키 → master DB key)
# 복합제(combination=True)의 ingredient_names는 개별 단일 성분명과 동일하므로
# 인덱스에서 제외해 단일 성분 엔트리가 덮어씌워지는 것을 방지한다.
_NAME_INDEX: dict[str, str] = {}
for _key, _entry in DRUG_MASTER_DB.items():
    _is_combo = _entry.get("combination", False)
    if not _is_combo:
        for _n in _entry["ingredient_names"]:
            _idx_key = _n.lower().replace(" ", "")
            if _idx_key not in _NAME_INDEX:
                _NAME_INDEX[_idx_key] = _key
    for _n in _entry["product_names"] + _entry.get("aliases", []):
        _idx_key = _n.lower().replace(" ", "")
        if _idx_key not in _NAME_INDEX:
            _NAME_INDEX[_idx_key] = _key


def _normalize_text(s: str) -> str:
    """소문자 변환 + 공백·특수문자 제거 (검색용)."""
    return re.sub(r"[\s\-_·/+·]", "", s.lower())


# 용량 패턴 (raw_name에 포함된 경우 strength 필드로 분리)
# 긴 단위를 앞에 두어 mcg가 mg으로 오탐되지 않도록 함.
# \b 제거: 한글·특수문자 혼재 환경에서 word boundary가 불안정하므로 생략.
_STRENGTH_EXTRACT_RE = re.compile(
    r"(\d+(?:\.\d+)?\s*(?:mcg|mEq|µg|ug|mg|ml|IU|tab|cap|정|캡슐|g))",
    re.IGNORECASE,
)


# ──────────────────────────────────────────────────────────────────────────────
# Provider 인터페이스
# ──────────────────────────────────────────────────────────────────────────────
class DrugMasterProvider(ABC):
    @abstractmethod
    def search_by_name(self, name: str) -> list[NormalizedDrug]: ...

    @abstractmethod
    def search_by_ingredient(self, ingredient: str) -> list[NormalizedDrug]: ...

    @abstractmethod
    def resolve_code(self, code: str) -> NormalizedDrug | None: ...

    @abstractmethod
    def split_combination(self, name: str) -> list[NormalizedDrug]: ...


class LocalDrugMasterProvider(DrugMasterProvider):
    """DRUG_MASTER_DB dict 기반 로컬 구현."""

    def _entry_to_normalized(self, key: str, entry: dict) -> NormalizedDrug:
        return NormalizedDrug(
            raw_name=key,
            normalized_name=entry["normalized_name"],
            ingredient_code=entry.get("ingredient_code"),
            ingredient_names=entry.get("ingredient_names", []),
            drug_class=entry.get("drug_class"),
            is_combination=entry.get("combination", False),
            components=entry.get("components", []),
        )

    def search_by_name(self, name: str) -> list[NormalizedDrug]:
        norm = _normalize_text(name)
        # 1단계: exact match
        if norm in _NAME_INDEX:
            key = _NAME_INDEX[norm]
            return [self._entry_to_normalized(key, DRUG_MASTER_DB[key])]
        # 2단계: partial match (포함 관계)
        results = []
        for idx_key, db_key in _NAME_INDEX.items():
            if norm in idx_key or idx_key in norm:
                entry = DRUG_MASTER_DB[db_key]
                nd = self._entry_to_normalized(db_key, entry)
                if nd not in results:
                    results.append(nd)
        results.sort(key=lambda nd: (
            1 if nd.is_combination else 0,
            0 if nd.ingredient_code else 1,
            abs(len(norm) - len(_normalize_text(nd.normalized_name))),
        ))
        return results[:3]

    def search_by_ingredient(self, ingredient: str) -> list[NormalizedDrug]:
        norm = _normalize_text(ingredient)
        results = []
        for key, entry in DRUG_MASTER_DB.items():
            for ing in entry.get("ingredient_names", []):
                if norm in _normalize_text(ing) or _normalize_text(ing) in norm:
                    results.append(self._entry_to_normalized(key, entry))
                    break
        return results

    def resolve_code(self, code: str) -> NormalizedDrug | None:
        for key, entry in DRUG_MASTER_DB.items():
            if entry.get("ingredient_code") == code:
                return self._entry_to_normalized(key, entry)
        return None

    def split_combination(self, name: str) -> list[NormalizedDrug]:
        """복합제 이름 → 성분별 NormalizedDrug 리스트."""
        parts = re.split(r"[/+]", name)
        if len(parts) < 2:
            return []
        results = []
        for part in parts:
            found = self.search_by_name(part.strip())
            if found:
                results.append(found[0])
        return results


# 싱글톤 인스턴스 (inference.py 등에서 import해서 사용)
drug_provider = LocalDrugMasterProvider()


def normalize_drug_name(raw_name: str) -> NormalizedDrug:
    """raw_name → NormalizedDrug. 용량 정보가 포함된 경우 strength 필드로 분리."""
    # raw_name에서 용량 추출 후 정규화된 약물명만 남김
    sm = _STRENGTH_EXTRACT_RE.search(raw_name)
    extracted_strength = sm.group(1).strip() if sm else None
    lookup_name = _STRENGTH_EXTRACT_RE.sub("", raw_name).strip()
    lookup_name = re.sub(r"\s+", " ", lookup_name).strip() or raw_name

    # 복합제 먼저 시도
    if re.search(r"[/+]", lookup_name):
        components = drug_provider.split_combination(lookup_name)
        if len(components) >= 2:
            comp_normalized = " / ".join(c.normalized_name for c in components)
            comp_keys = [c.raw_name for c in components]
            return NormalizedDrug(
                raw_name=raw_name,
                normalized_name=comp_normalized,
                ingredient_code=None,
                ingredient_names=[n for c in components for n in c.ingredient_names],
                drug_class="+".join(c.drug_class or "" for c in components),
                is_combination=True,
                components=comp_keys,
                strength=extracted_strength,
            )

    results = drug_provider.search_by_name(lookup_name)
    if results:
        r = results[0]
        return NormalizedDrug(
            raw_name=raw_name,
            normalized_name=r.normalized_name,
            ingredient_code=r.ingredient_code,
            ingredient_names=r.ingredient_names,
            drug_class=r.drug_class,
            is_combination=r.is_combination,
            components=r.components,
            strength=extracted_strength,
        )

    # 매칭 실패 — 용량 제거된 이름으로 보존
    return NormalizedDrug(
        raw_name=raw_name,
        normalized_name=lookup_name,
        ingredient_code=None,
        ingredient_names=[lookup_name],
        drug_class=None,
        is_combination=False,
        components=[],
        strength=extracted_strength,
    )
