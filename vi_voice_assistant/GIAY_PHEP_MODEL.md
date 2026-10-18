# Mã nguồn, model và dữ liệu giọng nói: các quyền khác nhau

> Đây là hướng dẫn kỹ thuật, không phải tư vấn pháp lý hay xác nhận giấy phép
> upstream. Phải đọc LICENSE/NOTICE/model card đúng phiên bản trước phân phối.

## 1. Mã nguồn dự án

`pyproject.toml` khai báo giấy phép mã nguồn là **MIT**. Thông tin này không tự
cấp quyền cho trọng số model, dataset, audio mẫu hay dịch vụ mà chương trình gọi.
Maintainer cần hoàn thiện tệp LICENSE/copyright notice phù hợp trước phân phối;
không suy luận từ tên tài khoản rằng mọi tài sản ngoài repo cùng một chủ sở hữu.

## 2. Backend được chọn quyết định điều kiện áp dụng

| Thành phần | Thông tin/việc cần kiểm tra |
| --- | --- |
| VieNeu (`giong_noi_ai.py`) | Repo khai báo Apache 2.0 cho preset đang dùng. Cần kiểm lại code, weights và dataset đúng phiên bản; giữ LICENSE/NOTICE và thông báo bắt buộc khi phân phối. |
| Piper (`PIPER_MODEL`) | Binary và từng voice/model có giấy phép riêng. Không áp một giấy phép chung cho mọi file ONNX mà người dùng cung cấp. |
| MMS-Vie/nhánh NC (`giong_nc.py`) | Repo ghi `CC BY-NC 4.0`; điều kiện phi thương mại áp dụng cho model tương ứng, không phải kết luận cấm thương mại toàn bộ dự án. |
| PhoBERT/PhoWhisper/checkpoint khác | Kiểm model card/giấy phép của checkpoint cụ thể, dữ liệu huấn luyện và phiên bản; không chỉ nhìn giấy phép thư viện Transformers. |
| Google STT/gTTS | Dịch vụ mạng có điều khoản riêng; audio/văn bản được gửi ra ngoài máy khi người dùng chọn hoặc cho phép cloud. |

Không dùng câu “Apache không cần ghi công” để bỏ LICENSE/NOTICE: nghĩa vụ cụ thể
phải đối chiếu giấy phép và tài sản phân phối. Không suy luận “code MIT/Apache”
đồng nghĩa trọng số, dữ liệu và output đều được dùng cho mọi mục đích thương mại.

## 3. Privacy mặc định từ v7.11

- STT `auto` thử backend local; Google phải chọn `--stt-engine google` hoặc cho
  phép fallback bằng `--allow-cloud-stt`.
- TTS auto/cache không tự dùng gTTS; chọn `--engine gtts` hoặc bật
  `--allow-cloud-tts` là cho phép gửi văn bản.
- `--stt-download` chỉ cho phép tải model STT chưa có; không phải quyền upload audio.
- VieNeu được chọn tường minh có thể tải model lần đầu. Auto chỉ reuse instance
  VieNeu đã khởi tạo, không khởi tạo model đó ngầm.
- Các cờ kỹ thuật không thay thế sự đồng ý/quyền xử lý dữ liệu của người được ghi âm.
  Không xem chương trình là network sandbox cho plugin Python hay binary bên ngoài.

## 4. Nhân bản giọng

Chỉ dùng audio mẫu mà bạn có quyền sử dụng và có sự đồng ý phù hợp của người có
giọng nói. Việc ghi âm thuộc sở hữu của bạn không mặc nhiên đồng nghĩa mọi quyền
liên quan đến người nói đã được giải quyết. Không dùng tính năng để giả mạo hay
khiến người nghe hiểu sai nguồn phát ngôn.

## 5. Tham khảo các nguồn được cấu hình trong repo

- VieNeu code: https://github.com/pnnbao97/VieNeu-TTS
- Preset VieNeu: https://huggingface.co/pnnbao-ump/VieNeu-TTS-v3-Turbo
- MMS-Vie: https://huggingface.co/facebook/mms-tts-vie

Các đường dẫn là tham khảo cấu hình, chưa được coi là bằng chứng rằng model/version
và giấy phép upstream đã được xác minh trong sandbox này. Người phát hành phải
kiểm lại trực tiếp trước khi phát hành hoặc sử dụng thương mại.
