"""
QR 코드 생성 스크립트 — 1회 실행 후 출력된 PNG를 인쇄해 병원 벽에 부착.

사용법:
  python scripts/generate_qr.py --url http://병원서버주소/upload.html
  python scripts/generate_qr.py --url http://192.168.1.100:8000/upload.html
"""
import argparse
import qrcode
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True, help="업로드 페이지 URL")
    parser.add_argument("--out", default="qr_upload.png", help="출력 파일명")
    args = parser.parse_args()

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=12,
        border=4,
    )
    qr.add_data(args.url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    out_path = Path(args.out)
    img.save(out_path)
    print(f"QR 코드 저장 완료: {out_path.resolve()}")
    print(f"URL: {args.url}")


if __name__ == "__main__":
    main()
