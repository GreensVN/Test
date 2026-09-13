# Giấy phép mô hình AI được sử dụng

> **Đọc trước khi dùng dự án này.**
>
> Mã nguồn trong repo này là mã nguồn mở. Các **mô hình giọng nói**
> mà nó gọi tới thì **không**. Đó là hai giấy phép tách rời nhau.

## Mã nguồn

Toàn bộ code trong repo: giấy phép MIT. Xem `LICENSE`.

## Mô hình giọng nói

Repo này **không chứa** file trọng số mô hình. Script sẽ tải về khi
bạn chạy lần đầu. Khi tải, bạn chấp nhận giấy phép của mô hình đó:

### facebook/mms-tts-vie

- Nguồn: https://huggingface.co/facebook/mms-tts-vie
- Giấy phép code: `CC BY-NC 4.0`
- Giấy phép trọng số: `CC BY-NC 4.0`
- **Phi thương mại.** Không được dùng để tạo doanh thu.

## Điều này nghĩa là gì với bạn

| Bạn muốn | Được phép |
| --- | --- |
| Đọc, sửa, fork mã nguồn | Có |
| Dùng cho cá nhân, học tập, nghiên cứu | Có |
| Đăng bản sửa đổi lên GitHub | Có |
| Bán app, chạy SaaS, gắn quảng cáo | **Không** |
| Dùng audio sinh ra trong video kiếm tiền | **Không** |

Muốn thương mại: thay bằng VieNeu-TTS v3-Turbo (Apache 2.0), hoặc nhân bản
giọng của chính bạn từ 3-5 giây audio mẫu (không cần fine-tune). Xem
`giong_noi_ai.py`.

## Ghi công

- facebook/mms-tts-vie — CC BY-NC 4.0 — https://huggingface.co/facebook/mms-tts-vie

---

*Đây là tóm tắt kỹ thuật, không phải tư vấn pháp lý. Hãy đọc bản
giấy phép gốc tại link ở trên trước khi phát hành.*
