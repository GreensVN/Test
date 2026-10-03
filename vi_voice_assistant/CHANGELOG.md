# CHANGELOG

## v7.9 (bổ sung 7) - Đừng biến lời nói thường thành LỆNH trên máy thật; 945 test

Ba lỗi dưới đây có cùng một hình dạng: trợ lý làm MỘT VIỆC KHÁC với điều
người dùng nói, và người dùng không có tín hiệu nào để biết. Nghiêm trọng hơn
mọi lỗi "ra số sai" ở các bổ sung trước, vì nó là lỗi **trên máy thật**.

**1. `SYSTEM_KEYWORDS` không có ranh giới từ.** `lock` khớp NẰM TRONG `clock`
và `unlock`, nên **"alarm clock" bị KHOÁ MÁY THẬT**. Tương tự `sleep` khớp
trong `asleep`. Nay mọi mẫu bọc `\b` hai đầu - thêm một từ khoá sau này cũng
không phải nghĩ lại chuyển này.

**2. `smart_normalize` tự sửa lỗi gõ thành từ khoá hệ thống.** "alarm clock" ->
"alarm **lock**", "tôi đang asleep" -> "tôi đang **sleep**" rồi máy ngủ thật.
Đây là lớp sửa CHỒNG lên lớp 1: vá `SYSTEM_KEYWORDS` một mình là không đủ,
vì câu đã bị đổi thành một từ đứng riêng trước khi tới đó.

**3. "đọc báo hôm nay" bị đoán `get_weather` ở 0.70** -> trợ lý mở thời tiết rồi
đọc ra *"Đang xem thời tiết đọc báo"*. "hôm nay" là dấu hiệu thời tiết rất
mạnh, còn "đọc báo" là động từ hiếm. Đã thêm cơ chế cứu theo từ khoá rõ ràng -
cùng cách đã làm cho toán ở bổ sung 4, và cùng giữ nguyên ngưỡng tự tin cho
câu mơ hồ.

**Vì sao chọn BỎ 22 lỗi gõ thật thay vì nâng ngưỡng sửa lỗi.** Đã đo trước khi
quyết định: độ tương đồng của lỗi gõ THẬT (`slep`->`sleep` 0.889,
`hutdown`->`shutdown` 0.875) **trùng** với từ tiếng Anh bị bắt (`clock`->`lock`
0.889, `asleep`->`sleep` 0.909). Hai nhóm chồng lên nhau ở 0.86-0.91, nên
**không có ngưỡng nào tách được**. Vì vậy chọn theo chi phí: sửa sai một từ
thường thì người dùng gõ lại được; sửa sai thành lệnh khoá máy/ngủ/shutdown thì
hậu quả là hành động thật và người dùng không biết vì sao. Bỏ 22 lỗi gõ thật để
đổi lấy việc không khoá nhầm máy là chấp nhận đáng kể, và được ghi lại đây
thay vì giấu đi.

**"hôm nay" cố ý KHÔNG đưa vào danh sách từ khoá rõ ràng.** Nó nằm trong cả
"đọc báo hôm nay", "lịch hôm nay" và "thời tiết hà nội hôm nay" - dẫn chứng yếu
hơn cả cụm động từ. Bộ test có một guard riêng chống lại việc ai đó thêm
"đọc báo" vào danh sách intent khác rồi nuốt luôn câu hỏi thời tiết.

**Kiểm chứng.** 945 test: `pytest -q` -> `945 passed`; `ruff check` 0; `mypy` 0
lỗi trên **52** file. 38 test mới trong `test_v79_intent_safety.py`, **12 FAIL**
trên `intent_model.py` + `nlu_advanced.py` trước khi sửa. Chạy thật:
"alarm clock" và "tôi đang asleep" không còn khoá/ngủ máy, còn "khoá máy",
"ngủ đi", "tắt máy", "mo chorme" -> "mở chrome" vẫn chạy.

**Ghi chú môi trường (quan trọng cho người đọc PR).** Trong lúc làm bổ sung này
môi trường cục bộ bị thay (repo được clone lại, mất toàn bộ lịch sử git cục
bộ, và `.venv` biến mất). Công việc đã commit trước đó vẫn còn nguyên trên
GitHub ở `c98b326` và đã được khôi phục lại; phần chưa commit của bổ sung này
đã viết lại và kiểm chứng lại từ đầu. Các con số trong mục này đều đo lại sau
khi khôi phục, không phải số của lần chạy trước.


## v7.9 (bổ sung 6) - Căn bậc N: `sqrt`, `√`, và lỗi đọc SAI SỐ; 907 test

**Nguy hiểm ở đây không phải là thiếu, mà là SAI.** "căn 2 của 8" cho 1.4142 -
nghĩa là đọc nhầm **số bị căn**: người Việt viết tắt "căn 2" cho "căn bậc 2",
nhưng bản cũ chỉ nhận đúng cụm "căn bậc 2". Thiếu chữ "bậc" thì con số 2 bị
nuốt làm số bị căn. Tệ hơn hẳn "chưa tính được": sai mà vẫn trông như một kết
quả hợp lệ, nên người dùng không có gì để nghi ngờ. Cùng cả "căn bậc 3 của 27"
ra 1.7321 thay vì 3.

**`√` bị `normalize_text()` XOÁ MẤT trước khi ai kịp nhìn thấy.** `_KEEP_RE`
lọc "mọi thứ ngoài `\w\s./:\-`", nên "√16" thành "16" - mất trọn dấu hiệu
"đây là căn bậc hai", và trợ lý báo *"chưa tính được phép tính 16"*. Vá ở
`_KEEP_RE` (tầng chuẩn hoá chung) chứ không riêng trong parser toán, vì
`predict_intent` cũng dựng entity từ chính câu đã chuẩn hoá - vá trong parser
thì parser nhìn thấy `√` mà tầng trên đã xoá mất. Sau khi vá: "√16" → 4.

**`square root of 16` bị model đoán thành `get_datetime`.** Chữ "time" trong
"root" đủ để model bịa ra ý nghĩa về giờ, và câu toán hoàn toàn xác định thì
đáng lẽ không có cách đọc nào khác. Đã thêm vào danh sách từ khoá toán rõ ràng.

**Nghiệm không tồn tại thì trả `None`, không bịa số.** Căn bậc chẵn của số âm
(căn bậc 2 của -4) không có nghiệm - bản cũ trả `None` và đúng, giữ nguyên.
Căn bậc lẻ của số âm thì CÓ nghiệm âm (căn bậc 3 của -8 = -2), nay tính đúng.
Căn bậc 4, 5 cũng nhận, vì "căn 4 của 16" là câu hỏi thật chứ không phải lỗi gõ.

**Một kỳ vọng test của tôi sai, đã sửa chứ không vòng qua.** Tôi viết
`căn bậc hai của căn bậc hai của 256` = 4, nhưng hành vi có từ trước (và hợp lý
hơn) là 16 - chỉ căn NGOÀI cùng được tính. Sửa kỳ vọng, không sửa hành vi.

**Kiểm chứng.** 907 test: `pytest -q` → `907 passed`; `ruff check` 0; `mypy` 0
lỗi trên **51** file. 54 test mới trong `test_v79_math_root.py`, **21 FAIL** trên
`intent_model.py` + `text_utils.py` trước khi sửa. Bộ test có phần bảo vệ
`_KEEP_RE` không hỏng đường dẫn và tên biến (`a-b_c`, `C:\Users\me`, `./run.sh`)
vì lần vá đầu làm rơi dấu `-`, làm hỏng đúng những thứ đó.


## v7.9 (bổ sung 5) - Nhắc theo ngày trong tuần; 853 test

**Bug nguy hiểm nhất từ trước đến nay: nhắc nhớ SAI NGÀY mà không hề báo.**
"nhắc tôi họp 9 giờ sáng thứ hai" cho `day_offset = 0`, tức đặt nhắc **ngay hôm
nay**, dù câu nói rõ là thứ hai. Ngày đó chỉ còn nằm lại trong nội dung nhắc
dưới dạng chữ, nên trợ lý đặt đúng giờ sai ngày - và người dùng tin là mình đã
đặt nhầm. Cùng lớp lỗi với "sau 3 ngày" ở v7.8, chỉ khác ở chỗ dạng này cần
**lịch thật** chứ không chỉ đếm số. Nay dùng `calendar` + `datetime.date.today()`.

**Ba chỗ đã sửa, mỗi chỗ một kiểu sai khác nhau.**

*Ngày trong tuần bị nuốt mất.* `_parse_relative_day` của v7.8 so mẫu
`(\d+)\s*(ngay|tuan|thang)`, nên "9 giờ sáng thứ 4 **tuần sau**" ra "4 tuần"
= **28 ngày**. Con số 4 là của "thứ 4"; "tuần sau" chỉ là dấu hiệu khoảng cách
chứ không có số đi kèm. Câu có tên ngày nay thuộc về `_parse_clock` và được
chặn lại ở cả `_parse_delay` lẫn `_parse_relative_day`.

*`0` là falsy.* `map.get(k) or map.get(k2)` với "thứ hai" (giá trị 0) rơi xuống
nhánh dự phòng rồi ra `None`, khiến **mọi** câu "thứ hai" đều ra offset 0. Cùng
kiểu với `config.get("port") or 8000` mà cổng 0 không hợp lệ - ở đây 0 lại đúng.

*"tôi" trùng "tới" khi bỏ dấu.* So `\b(?:toi|den|sau|next)\b` trên cả câu thì
"nhắc **tôi** họp 9 giờ sáng thứ tư" bị đọc thành "thứ tư **tới**" và đẩy sang
tuần sau. Nay từ này phải đứng liền sau tên ngày. Sai lệch đúng 7 ngày, và sai
đúng vào hôm nay - tức nhắc sớm ngay lúc người dùng cố nói "TUẦN SAU".

**Quy ước đã chọn, vì đều có cái giá.** "cuối tuần" lấy **Chủ nhật** chứ không
phải thứ Bảy (thứ Bảy vẫn có thể làm việc, chọn nó là khiến người dùng phải
đi làm cuối tuần). "cuối tháng" dùng `calendar.monthrange` nên tháng 2 năm
nhuận ra 29, không phải 28. "đầu tuần" luôn ít nhất 1 ngày vì nói "đầu tuần" vào
đúng thứ hai thì vô nghĩa.

**Câu xác nhận phải nói ra ngày.** Nó vốn chỉ đọc "9 giờ 0 phút", nên câu
"...thứ hai" và câu "...mai" cho **cùng một** câu trả lời. Nay thêm ngày khi
mốc giờ không rơi vào hôm nay.

**Một test cũ phải SỬA, vì nó đang giữ kỳ vọng sai.** "gặp bạn 3 giờ chiều
thứ hai" từng được kỳ vọng giữ lại chữ "thứ hai" trong nội dung. Kỳ vọng đó
đúng **khi parser chưa hiểu "thứ hai"** - ngày chỉ còn trong chữ, lịch rơi về
hôm nay. Nay parser đã tra lịch thật nên chữ đó chỉ là nhiễu. Test không bị
xóa mà được đổi thành kiểm tra cả hai vế: nội dung sạch **và** ngày rơi đúng
thứ hai.

**Kiểm chứng.** 853 test: `pytest -q` → `853 passed`; `ruff check` 0; `mypy` 0
lỗi trên **50** file. 65 test mới trong `test_v79_calendar_weekday.py`, **37 FAIL**
trên `intent_model.py` trước khi sửa (đo bằng cách thay source cũ + 2 hàm giả
để test import được). Bộ test lịch dùng `today` **CỐ ĐỊNH** cho các case
"ngày cụ thể" - một bộ test lịch mà chạy đúng vào thứ Hai thì fail vào thứ Ba
là bộ test vô dụng. Chạy thật: "9 giờ sáng thứ hai" → *"9 giờ 0 phút thứ hai tuần
sau"*, "cuối tuần" → *"chủ nhật tuần sau"*, "thứ 4 tuần sau" → đúng 1 tuần.

**Còn lại, chưa sửa.** `sqrt 144` (chưa có toán tử căn bậc hai viết tắt);
75 khoá `ACCENT_MAP` mơ hồ (`"thoi tiet ha noi"` → `hà nói` thay vì `Hà Nội`) -
đo thử quy tắc ưu tiên theo dataset cải thiện **0/75**, cần từ điển tần suất
thật. GitHub Actions chưa từng chạy (token không có quyền Actions).


## v7.9 (bổ sung 4) - Logarit và phần dư; 788 test

`log`, `ln`, `mod` thiếu khá lâu, và cái thiếu đó **im lặng**: người gõ đúng câu
toán rồi nhận về *"chưa tính được"* - y hệt lỗi `12% của 200` mà v7.8 đã sửa.

**Mặc định của "log" là chỗ dễ sai nhất, và sai thì ra CON SỐ SAI chứ không
ra lỗi.** Trong toán Việt, `log` không nói cơ số là cơ số **10**; còn phần lớn
máy tính điện tử và mọi công cụ lập trình dùng `log` để chỉ ln. Theo quy ước
kỹ thuật thì `"log 100"` ra 4.605 thay vì 2 - và câu mô tả nghe rất hợp lệ, nên
người dùng rất dễ tin là mình sai. Đây là lý do chọn quy ước Việt: chọn sai thì
ít nhất phải sai *đúng toán học*. Chỗ nào người dùng đã nói rõ thì theo họ:
`ln` = cơ số e, `log2`/`log3` = cơ số viết liền, `"log 8 cơ số 2"`.

**`fixed_base` nuốt chữ số đầu.** Cho phép mẫu số tùy ý không ràng buộc thì
`"log 100"` bị tách thành cơ số `"10"` và số `"0"`, ra 10⁰ = 1 thay vì log₁₀(100)
= 2. Nay cơ số viết liền chỉ nhận `10` hoặc `2`-`9`, đứng ngay sau `log`.

**Phần dư có HAI thứ tự từ, thiếu một là ra số sai.** Tiếng Anh `"5 mod 3"` là
(số, từ, số); tiếng Việt `"100 chia 7 lấy dư"` đặt cụm `"lấy dư"` ở **cuối**.
Chỉ nhận thứ tự thứ nhất thì câu tiếng Việt rơi xuống nhánh `"chia"` và ra
**14.28** thay vì 2 - sai mà vẫn trông như một phép chia bình thường.

**Từ khoá toán KHÔNG THỂ nhầm thì cứu được, kể cả khi model tự tin.** Model đoán
`system_control` cho `"log 8 cơ số 2"` (0.62) là sai hiển nhiên: không có cách đọc
nào khác ngoài toán. Ngưỡng tự tin 0.5 của v7.8 **được giữ nguyên** cho câu mơ
hờ như `"15 + 27"` (có thể là số phiên bản) - mở rộng cứu chỉ cho từ khoá rõ
ràng, và vẫn cần câu đó thật sự ra một biểu thức tính được.

**Chi tiết đáng ghi:** danh sách từ khoá rõ ràng phải so trên bản **bỏ dấu**.
Câu `"100 chia 7 lấy dư"` viết có dấu còn các mẫu toán viết không dấu (đúng quy
ước mọi mẫu khác trong file) - so trên câu gốc thì câu tiếng Việt không bao giờ
khớp. Đây đúng là lỗi đã làm `"2 ngày nữa"` im lặng ở bổ sung trước, lặp lại ở
chỗ khác vì cùng một nguyên nhân.

**Kiểm chứng (đo, không ước lượng).** 788 test: `pytest -q` → `788 passed`;
`ruff check` 0; `mypy` 0 lỗi trên **49** file. 39 test mới, trong đó **29 FAIL
trên `intent_model.py` trước khi sửa**; 10 test còn lại là các case phải giữ
nguyên (`"15 + 27"` vẫn được bảo vệ bởi ngưỡng tự tin của v7.8, `"5 chia 3"`
vẫn là phép chia). Chạy thật qua `--once`: `log 100` → 2, `ln 100` → 4.6052,
`log2 1024` → 10, `log 8 cơ số 2` → 3, `5 mod 3` → 2, `100 chia 7 lấy dư` → 2.

**Còn lại, chưa sửa.** `"nhắc tôi họp sáng mai"` còn để lại `"sáng mai"` trong nội
dung nhắc; `cuối tuần`/`cuối tháng`/`thứ hai tuần sau` (cần lịch thật); 75 khoá
`ACCENT_MAP` mơ hồ (`"thoi tiet ha noi"` → `hà nói` thay vì `Hà Nội`) - đo thử
quy tắc ưu tiên theo dataset cải thiện **0/75**, cần từ điển tần suất thật.


## v7.9 (bổ sung 3) - Chỗ để trống `unknown` không được lọt ra miệng người dùng; 749 test

Lỗi cuối trong danh sách, và nặng hơn các lỗi "sai intent" khác vì nó **tự
tin**: model đoán `open_app` với **0.97**, rồi `extract_entity` trả về chuỗi
`"unknown"`. Trợ lý đáp *"Chưa biết ứng dụng 'unknown'. Hãy thêm 'unknown' vào
config.json"* - vừa vô nghĩa, vừa dạy người dùng sửa sai file cấu hình.

**Nguyên nhân không phải stop-word thừa, nên cũng không sửa bằng cách bớt đi.**
`STOP_WORDS_ALL` phải chứa "trình"/"duyệt" để câu dài bỏ đúng phần đó ("mở
trình duyệt youtube" → `youtube`). Nhưng với câu NGẮN đúng bằng chỗ đó thì bỏ
hết rồi không còn gì để gọi tên. Bỏ bớt stop-word sẽ hỏng câu dài, mà câu dài
là phần lớn các câu.

Cách sửa là **bỏ dần**: `_entity_default` bỏ hết stop-word, và nếu ra chuỗi
rỗng thì bỏ tiếp động từ lệnh (`mở`, `chạy`, `bật`...) rồi lấy phần còn lại.
`"mở trình duyệt"` → `trình duyệt`, còn `"mở trình duyệt youtube"` vẫn ra
`youtube` như cũ.

**`system_control` in thẳng chỗ để trống ra cho người dùng đọc.** `"máy tính"`
là câu lệnh nửa vời: `_system_action` không khớp từ khóa nào nên trả
`"unknown"`, rồi executor in *"Không hỗ trợ lệnh hệ thống 'unknown' trên
Linux"* - tự thừa nhận là không hiểu mà không giúp người dùng nói tiếp được.
Nay hỏi lại đúng cách `action_search_web` đã làm sẵn từ trước cho chỗ để trống.

**Kiểm chứng (đo, không ước lượng).** 749 test: `pytest -q` → `749 passed`;
`ruff check` 0; `mypy` 0 lỗi trên **48** file. 15 test mới, trong đó **6 FAIL
trên đúng hai file nguồn trước khi sửa**; 9 test còn lại là các case phải giữ
nguyên (`"mở trình duyệt youtube"` vẫn phải ra `youtube`, lệnh hệ thống thật
vẫn phải chạy). Chạy thật qua `--once`: `"mo trinh duyet"` ra *"Chưa biết ứng
dụng 'trình duyệt'. Hãy thêm vào app_map_linux..."* (gọi đúng tên), `"may
tinh"` ra *"Bạn muốn làm gì với máy tính ạ?"*.

**Còn lại, chưa sửa.** Intent sai vẫn còn, chỉ là không còn tự tin đến mức vô
lý nữa: `"chat giup toi"` → `play_media` 0.84, `"lac wifi"` → `play_media` 0.44,
`"bat den"` → `play_media` 0.22 (ba câu này đều dưới ngưỡng nên bị hỏi lại, an
toàn). `"thoi tiet ha noi"` ra target `hà nói` thay vì `Hà Nội` - thuộc 75 khoá
`ACCENT_MAP` mơ hồ đã ghi ở v7.8, cần từ điển tần suất thật mới giải được.
`log`/`mod` trong toán học; `"nhắc tôi họp sáng mai"` còn để lại "sáng mai" trong
nội dung nhắc; `cuối tuần`/`thứ hai tuần sau` (cần lịch thật).


## v7.9 (bổ sung 2) - STT: đừng đánh đổi vĩnh viễn vì một lần lỗi; 734 test

Cả ba lỗi dưới đây cùng một dạng: **lỗi bị nuốt rồi biến thành hành vi sai**,
không phải thành thông báo lỗi. Người dùng không biết trợ lý đã chuyển sang
chế độ khác, và cũng không biết vì sao.

**Một lần tải model hỏng thì bỏ offline VĨNH VIỄN.** `_load_model` ghim
`_use_google` ngay lần thất bại đầu tiên, và `_load_model` mở đầu bằng
`if self._pipe is not None or self._use_google: return` - nên một lần lỗi tải
(mạng chập chờn lúc tải ~1GB, đĩa bận một lát) giáng phiên đó xuống STT đám
mây **vĩnh viễn**, và âm thanh người dùng bắt đầu nằm trên máy người khác mà
không ai báo. Nay thử tối đa 3 lần trước khi bỏ. Phải có giới hạn: thử vô hạn
là treo máy lúc khởi động.

**Nuốt mọi lỗi thành `return ""` khiến "mất mạng" nghe như "nói không ra".**
`_google_from_array`/`_google_from_file` bắt `Exception` rồi trả `""` - người
dùng nghe im và tưởng mình nói không ra, trong khi thật ra là mất mạng hoặc hết
hạn mức. Hai chuyện cần hai cách xử lý khác nhau (nói lại vs gõ tay), và hàm
`listen_once` ở tầng trên **vốn đã phân biệt được** (`UnknownValueError` vs
`RequestError`); lớp `STT` thì không. Nay dùng chung cách phân biệt đó, và chỉ
cảnh báo lần đầu + mỗi 10 lần liên tiếp để không thành spam trong lúc dùng.

**Bộ đếm hỏng không được reset khi nghe lại được.** Lỗi của chính bản sửa đầu
tiên: chỉ nhánh "không nghe rõ" mới reset, còn lúc thành công thì không - nên
một lần mất mạng 3 giây giữa phiên làm bộ đếm leo lên mãi, và câu cảnh báo
*"lần 1001"* xuất hiện ở một câu nói hoàn toàn bình thường. Bắt được nhờ test
viết "hỏng rồi nghe lại được" thay vì chỉ kiểm chiều hỏng.

**Lỗi giải mã offline làm SẬT cả câu lệnh.** `transcribe_array`/
`transcribe_file` để lỗi từ `self._pipe(...)` nổ thẳng ra ngoài, trong khi đường
Google gặp lỗi cùng tình huống thì trả `""` êm. Không công bằng: một file âm
thanh hỏng đang giật người dùng về tận chỗ gõ lệnh.

**Kiểm chứng (đo, không ước lượng).** 734 test: `pytest -q` → `734 passed`;
`ruff check` 0; `mypy` 0 lỗi trên **47** file. 10 test mới, trong đó **7 FAIL
trên `stt.py` trước khi sửa**.

**Điểm yếu thật của bộ test này, nói thẳng:** máy CI không có
`transformers`/`torch`/`speech_recognition`/`numpy`, nên các test dựng hậu bối
giả cho đúng những chỗ v7.9 sửa. Nếu `_load_model` đổi tên biến, test vẫn xanh.
Các đường thật (tải model 1GB, gọi Google) **không được kiểm ở đây** và phải
thử tay trên máy có đủ thư viện.


## v7.9 (bổ sung) - Nhắc nhở lặp lại; 724 test

"mỗi ngày" là câu người dùng hỏi rất nhiều mà bản trước không có nơi để lưu.
Hệ quả là im lặng: mỗi lần đến giờ thì nhắc xong là **xoá hẳn khỏi danh sách**,
nên "uống thuốc mỗi ngày" chỉ nhắc đúng MỘT lần rồi thôi - và người dùng tin
là đã hẹn cả tháng, vì bản cũ chỉ hẹn một lần.

Nhịp lặp được đọc bằng `parse_repeat` (`mỗi/hằng` + ngày/tuần/tháng, hoặc buổi:
"mỗi sáng"), lưu thành trường `repeat` trong `reminders.json`, và mỗi lần nổ
thì lời nhắc tự hẹn lại lần kế. Câu xác nhận **nói ra nhịp lặp** ("Lặp lại mỗi
ngày") - không nói thì người dùng tưởng đã hẹn cả tháng trong khi thực ra chỉ
một lần.

**Nội dung nhắc nuốt mất môn đề.** `_reminder_task` không gỡ được "mỗi ngày",
nên trợ lý đọc thành *"Nhắc bạn: uống thuốc mỗi ngày"*. Tệ hơn nữa: `"đặt báo
thức 6 giờ sáng mỗi ngày"` để lại nội dung rỗng, rơi về mặc định `"mỗi ngày"` -
tức người dùng dặn báo thức 6 giờ sáng mỗi ngày và nhận được lời nhắc tên là
"mỗi ngày". Nay gỡ sạch, nên câu đó ra đúng `"báo thức"`.

**Lần sau phải GIỮ nhịp lặp - lỗi âm thầm đắt nhất của vòng này.** Bản đầu tính
mốc kế tiếp rồi bỏ luôn `repeat` khi gọi `_schedule_reminder`, nên nhắc hằng ngày
chạy đúng **hai** lần rồi hạ xuống thành nhắc một lần. Cả tháng đầu vẫn ngon nên
rất khó phát hiện bằng tay; chỉ lộ ra khi bắn hai lần liên tiếp rồi đọc lại
`reminders.json`.

**Lịch dài hơn trần `threading.Timer` phải chia chặng, và mỗi chặng phải được
phân biệt.** Windows trần ở ~49.7 ngày nên lặp hằng tháng cần chia chặng. Nếu
mỗi chặng bị coi là lần nhắc thật thì nó bắn tiếng và hẹn thêm một lịch mới -
một nhắc hằng tháng thành nhắc vài lần mỗi tháng. Nay chặng nối tiếp mang cờ
`continuation`: chỉ bật chặng kế, không báo, không hẹn lại.

**Mở lại máy thì phải CUỘN vòng, không phải nhích một bước.** Mốc giờ đã trôi qua
lúc máy tắt (ngủ qua giờ uống thuốc) phải cuộn tới lần kế tiếp. Cuộn đúng
**một** bước thì với lịch "mỗi ngày" bỏ sót một ngày là vẫn nằm trong quá khứ,
`_schedule_reminder` từ chối, và cả chuỗi biến mất - đúng cái hỏng mà hàm này
sinh ra để chặn. Có chặn 400 bước để đồng hồ hỏng không quay vô hạn.

**Nhịp lặp sống sót qua câu hỏi "mấy giờ?".** "uống thuốc mỗi ngày" chưa nói
giờ thì trợ lý hỏi lại; nếu không mang nhịp lặp qua câu hỏi thì câu trả lời sau
ra một lời nhắc một lần. Hành vi có ý thức sẵn có là người dùng nói sang chuyện
khác thì bỏ câu hỏi đang treo ("mở nhạc" không phải giờ nhắc) - nhịp lặp đi theo
cả hành vi này, không tự ý giữ lại.

**Rác trong `reminders.json` bị chặn lúc ĐỌC.** `repeat` do người dùng sửa tay có
thể là bất cứ thứ gì; lỗi đó phải bị `_coerce_repeat` chặn khi đọc chứ không phải
lúc nhắc nổ. `bool` bị lo có chủ đích: trong Python `isinstance(True, int)` là
True, nên `weekday=True` sẽ lọt vào phép tính ngày nếu không kiểm riêng. Ngày 31
tháng không có (31/1) được lùi về ngày cuối tháng thay vì nổ `ValueError`.

**Kiểm chứng (đo, không ước lượng).** 724 test: `pytest -q` → `724 passed`;
`run_tests.py -q` → `724 passed`; `ruff check` 0; `mypy` 0 lỗi trên **46** file.
45 test mới, trong đó **41 test FAIL trên đúng hai file nguồn trước khi sửa**
(kiểm bằng `git stash push`); 4 test còn lại là các case phải giữ nguyên. Chạy
thật: đặt lịch `uống thuốc` 8h daily, `họp` 9h thứ-Hai, `báo thức` 6h daily đều
ghi `repeat` vào `reminders.json`; bắn thật một lời nhắc 2 giây thì tự hẹn lại
ngày hôm sau **và giữ nguyên `repeat`**; lịch hằng tuần/tháng tính đúng (30/09 →
05/10 cho thứ Hai, 31/01 → 28/02 không nổ).

**Còn lại, chưa sửa.** "nhắc tôi họp sáng mai" để lại "sáng mai" trong nội dung
(cùng họ với lỗi ở phần trên nhưng là mốc giờ dạng "sáng mai", chưa gỡ); `log`
và `mod` trong toán học; STT ghim `_use_google` vĩnh viễn khi Google lỗi; intent
sai nhưng tự tin (`"mo trinh duyet"` → `open_app` với `target='unknown'` ở 0.97);
`cuối tuần`/`thứ hai tuần sau` (cần lịch thật); 75 khoá `ACCENT_MAP` mơ hồ (v7.8).


## v7.9 (2026-09-30) - Sửa lỗi thật ngoài phạm vi test; 679 test

Bộ test v7.8 xanh hoàn toàn, nên vòng này **không soi lại code cũ** mà đo trực
tiếp trên câu lệnh tự nhiên rồi sửa những chỗ sai. Bốn nhóm lỗi dưới đây đều
không có test nào chạm tới, và phần lớn cùng một dạng: **tính năng làm được
một nửa** - tầng trên hiểu, tầng dưới không, hoặc hai tầng hiểu khác nhau.

**Số học: `normalize_text` xoá mất `%` và `^`.** Hai ký hiệu này không khớp
`[^\w\s./:\\-]` nên bị lớp chuẩn hóa xoá trước khi parser kịp thấy: `"12% của
200"` và `"2^10"` trả `(None, None)`, trong khi `"15 + 27"` - đúng ví dụ trong
`--help` - chạy được. Người dùng gõ phép tính đúng mà không bao giờ được tính,
rồi kết luận máy hỏng. Cùng kiểu với lỗi dấu chấm ở v7.8: bước chuẩn hóa phía
trước ăn mất ký hiệu trước khi parser kịp phân tích.

Có hai chỗ phải sửa cùng lúc, vì chỉ sửa một chỗ thì `--once` vẫn hỏng:
`_protect_math_syntax` (giữ ký hiệu qua `normalize_text`) **và** `_MATH_SYNTAX_RE`
- mẫu này quyết định `entity_source` lấy từ câu gốc hay từ bản đã chuẩn hóa,
nên bỏ sót `%`/`^` thì tầng NLU vẫn tính trên bản đã bị xoá ký hiệu. Luỹ thừa
gộp thành MỘT token trước khi `*` bị đổi thành placeholder, nếu không `"2 ** 10"`
thành `"2 * * 10"` và biểu thức ghép không được. Biểu thức trả về được đọc thành
tiếng cho người dùng nên `**` đổi lại thành `^` ở chỗ hiển thị, **không** sửa
`_restore_math_syntax` (hàm đó chạy **trước** bước `eval`). Chỉ nhận `%` khi nó
đứng **sau một chữ số** và trước `"của"` - nên `"100% rồi"` và `"tăng âm lượng
20%"` vẫn không bị tính nhầm.

**Mốc giờ tính bằng ngày/tuần/tháng không tồn tại.** `"nhắc tôi họp sau 3 ngày"`
là câu rất tự nhiên, nhưng `parse_time_expression` chỉ biết giây/phút/giờ nên
rơi xuống cuối hàm và trả `type=None`. Nay `"sau 3 ngày"` → 4320 phút, `"2 ngày
nữa"` → 2880, `"sau 2 tuần"` → 20160, `"sau 1 tháng"` → 43200, `"ngày kia"` →
2880; đều phát ra dưới dạng `type="delay"` mà `executor._reminder_when()` đã xử
lý sẵn, nên không phải sửa gì ở tầng thực thi. Giữ nguyên chốt chặn an toàn của
`_parse_delay`: **bắt buộc có dấu hiệu khoảng cách** (`sau`/`nữa`), nếu không
thì "câu này dài 3 ngày" - một câu hỏi dài 3 ngày - cũng bị đọc thành nhắc nhở.

Chi tiết đáng ghi vì rất dễ làm sai: dấu hiệu `sau`/`nữa` được so trên bản **CÓ
DẤU** khi câu gõ có dấu, và trên bản bỏ dấu khi gõ không dấu. So mẫu có dấu với
bản bỏ dấu thì **không bao giờ trúng** (`nữa` → `nua`), và đó chính là lý do
`"2 ngày nữa"` im lặng. Đổi chiều thì lại hỏng tên riêng ("Sáu" → "sau"), nên
phải làm y hệt cách `_parse_delay` đang làm.

**Parser hiểu mốc giờ, phần bóc nội dung thì không.** Nhắc vẫn được đặt đúng
thời điểm, nhưng `_reminder_task` bóc mốc giờ bằng hai regex chỉ biết
"giờ/phút/tiếng" nên bỏ lại phần thời gian trong nội dung, và trợ lý đọc thành
*"Đến giờ rồi. Nhắc bạn: họp sau 3 ngày"* - tự nhắc lại chính mốc giờ như thể
đó là việc cần làm. Nay bóc thêm khoảng cách theo ngày/tuần/tháng và giờ viết
tắt kiểu tin nhắn (`"7h"`, `"6h30"`, `"7h tối nay"`), với đuôi hai từ giống hệt
`_REMINDER_TIME_RE` để `"7h tối nay"` không còn sót chữ `nay`.

**Lời nhắc có động từ rõ ràng bị đoán thành câu HỎI ngày giờ.** Chữ "ngày" trong
mốc giờ kéo model về `get_datetime` (0.44): `"nhắc tôi rửa xe ngày kia"` không
hề đặt nhắc, trợ lý chỉ đọc ngày giờ rồi im - trong khi người dùng đã nói rõ
"nhắc tôi". Nay `_rescue_reminder_intent` ép về `set_reminder`, theo **đúng
nguyên tắc an toàn đã dùng cho cứu câu toán ở v7.8**: chỉ sửa khi model **không
chắc** (dưới 0.5) và cả năm điều kiện đúng - model đoán `get_datetime`, câu MỞ
ĐẦU bằng động từ nhắc nhở, câu CÓ mốc giờ thật (`parse_time_expression` là bằng
chứng quyết định, không phải suy đoán từ ký tự), và câu **không phải câu hỏi
lịch**. Điều kiện cuối là chốt chặn quan trọng nhất: không có nó thì
`"nhắc tôi mai là thứ mấy"` - một câu hỏi thật - sẽ bị đổi thành lời nhắc.

**Còn lại, chưa sửa (cần quyền hoặc dữ liệu ngoài).** Lịch lặp lại
(`reminders.json` chưa có trường `repeat`); `cuối tuần`/`cuối tháng`/`thứ hai
tuần sau` - cần lịch, không suy từ câu rời; STT khi Google STT lỗi thì
`_use_google` bị ghim vĩnh viễn, không tự thử lại; intent sai nhưng tự tin
(`"mo trinh duyet"` → `open_app` với `target='unknown'` ở 0.97); `log`/`mod`; và
75 khoá `ACCENT_MAP` mơ hồ về bản thân việc phục hồi dấu (xem v7.8).

**Kiểm chứng (đo, không ước lượng).** 679 test: `pytest -q` → `679 passed`;
`ruff check` 0; `mypy` 0 lỗi (45 file). 35 test mới, trong đó **24 test FAIL
trên đúng file nguồn trước khi sửa** (đã kiểm chắc bằng `git stash push` chỉ
hai file nguồn) - 11 test còn lại là các case phải giữ nguyên, đúng như thiết
kế. Chạy thật qua `--once`: `12% của 200` → 24, `2^10` → 1024, `2 ** 10` →
1024, `12 phần trăm của 200` → 24, `15 + 27` → 42, `1.234,5 chia 3` → 411.5,
còn `100% rồi` vẫn báo không tính được. Hai lời nhắc ghi vào `reminders.json` đúng
ngày và nội dung sạch: `họp` → 2026-10-03, `rửa xe` → 2026-10-02 (không còn
dính "ngày kia").


## v7.8 (2026-09-27) - Số bị "bảo vệ" rồi hỏng; 644 test

Ba vòng trước soi chỗ nhận dữ liệu. Vòng này soi chỗ **giữ** dữ liệu, và lỗi
tìm được đều có cùng một dạng: **một lớp bảo vệ chạy trước làm hỏng thứ nó định
bảo vệ**. `normalize_text` xoá toán tử để câu nói dễ phân loại, rồi chính con số
bị mất dấu trong lớp bảo vệ đó.

**Số học: `target` và `result` nói hai đằng khác nhau.** Câu `"12,75 + 1"` cho
`target = "75 + 1"` (= 76) nhưng `result = 13.75` - vì `target` đi qua
`extract_entity` → `_EntityContext.raw` (đã bị `normalize_text` nuốt mất `12,`)
còn `result` đi qua `parse_math_expression(entity_source)`. Người dùng nhìn
thấy "75 + 1" cùng đáp án 13.75, không cách nào tự kiểm được. Nay `_entity_calculate`
ưu tiên câu GỐC, và `predict_intent` dùng câu gốc cho phần trích thực thể khi
thấy toán tử số (đúng cách nó đã làm với URL/đường dẫn từ v6).

**Dấu chấm là dấu PHẨY NGHÌN kiểu Việt Nam.** `"1.234,5 chia 3"` trả **78.17**
(= 234.5 / 3) thay vì 411.5: phần `1.` bị mất, và kết quả sai vẫn trông như
một phép tính bình thường - tệ hơn hẳn việc không tính được. Nay nhóm 3 chữ số
sau dấu chấm được đọc là nghìn (`1.234.567,89` → 1234567.89), còn `1.5`/`12.75`
(nhóm không đủ 3 số) vẫn là thập phân kiểu Anh như cũ. Nhóm đầu bắt đầu bằng `0`
(`0.250`) giữ nguyên - không ai viết "0.250" nghĩa là 250.

**`split_commands` cắt dấu phẩy thập phân.** `"2,5 nhân 4"` bị tách thành HAI
lệnh (`"2"` và `"5 nhân 4"`), lệnh đầu không phải lệnh tính, và câu đó ra 20 thay
vì 10. Nay phẩy chỉ tách khi không nằm giữa hai chữ số; `"mở chrome, phát nhạc"`
vẫu tách đúng như cũ.

**Câu toán hỏng dấu `+` còn bị model đoán nhầm intent.** `"1.234 + 5"` qua
`normalize_text` thành `"1.234 5"`; model đoán `system_control` với 0.20 (tưởng
là số phiên bản), người dùng gõ đúng biểu thức mà không bao giờ được tính. Nay
`_rescue_calculate_intent` ép về `calculate` **chỉ khi cả ba** điều kiện đúng:
model không đoán calculate, model không chắc (dưới 0.5), và câu gốc thật sự ra
một biểu thức tính được. Model chắc thì để model quyết - không cãi ý kiến đã
vững. `parse_math_expression` không nhận nhầm câu thường (đã thử "mở chrome",
"mấy giờ", "mở file report.pdf", "tìm bài hát abc"...).

**`parse_math_expression` hiểu cả câu gõ KHÔNG DẤU.** Bản cũ ghép regex CHỈ có
dấu, nên `"can bac hai cua 81"`, `"15 phan tram cua 200"`, `"16 binh phuong"`,
`"3 mu 2"` trả `(None, None)` - trong khi README quảng cáo "hiểu tiếng Việt có
dấu lẫn không dấu" và người gõ nhanh (hay cả STT) hay bỏ dấu. Nay nhận diện trên
bản bỏ dấu rồi hiển thị lại bằng tên CÓ DẤU; có test parity bắt buộc hai kiểu
gõ cho cùng kết quả và cùng câu mô tả.

**Ngưỡng tự tin: `NaN` đi thẳng qua cửa an toàn.** `nan < x` luôn False, nên
`execute_command` với `"confidence": NaN` BỎ QUA ngưỡng rồi chạy lệnh - mà JSON
của Python mặc định chấp nhận `NaN`/`Infinity`, và `--json` là đường dùng thật.
Tương tự, `NLU._judge` trả "ok" cho NaN (lệnh ĐƯỢC THỰC THI) và nổ `TypeError`
khi confidence là chuỗi. Nay `_read_confidence` chỉ nhận số hữu hạn trong `[0,1]`;
còn `nlu_advanced` dùng `_as_confidence` và `last_intent` không còn nổ `KeyError`.

**Dữ liệu bị đánh cắp bởi chính lớp bảo vệ.** `log_feedback` ghi vào một file
CSV **RỖNG** (mất điện) không ghi dòng tiêu đề; `train_nlu.py` đọc bằng
`csv.DictReader` nên ăn mất dòng đầu và **bỏ qua toàn bộ phần còn lại** - mọi câu
người dùng đã dạy biến mất khỏi huấn luyện. File không có header nay được sửa
lại trước khi ghi. Cùng kiểu: `lite_model` để lại file tạm khi ghi lỗi OSError
(đúng nhánh lỗi hay xảy ra nhất: đĩa đầy, thiếu quyền), và nhắc nhở được đăng ký
**sau** khi bộ đếm đã chạy nên lệnh huỷ ngay lập tức không tìm thấy nó.

**Sửa nguồn ghi mà không sửa nguồn đọc thì người dùng cũ vẫn mất dữ liệu.**
`train_nlu.py` đọc `feedback.csv` bằng `csv.DictReader`, mà `DictReader` coi
DÒNG ĐẦU là tên cột: file không có header thì dòng dữ liệu đầu bị ăn mất thành
tên cột và mọi dòng sau không còn khoá `verified` - kết quả **"0 câu"**, đúng bằng
câu "bạn chưa dạy gì", không hề có cảnh báo. Đây chính là file mà `log_feedback`
bản cũ tạo ra khi ghi vào một file rỗng (mục trên đã sửa nguồn ghi) - nên người
dùng đã có sẵn file hỏng trên đĩa, sửa nguồn ghi không cứu được họ. Nay đọc
chịu được cả bốn kiểu (header đầy đủ / thiếu cột phụ / không header), đọc theo
vị trí cột khi thiếu header, và **báo rõ** để người dùng biết file của họ có vấn
đề thay vì tưởng mình chưa dạy gì. `my_dataset.csv` (file người dùng tự viết
tay) nên thiếu dòng tiêu đề là chuyện rất bình thường.

**Cùng lỗi đó lặp lại ở một chỗ nữa — và cùng một file.**
`dataset.load_extra_csv` cũng dùng `csv.DictReader`, và nó đọc chính
`my_dataset.csv` mà `train_nlu` đọc. Khi file thiếu tiêu đề, cả hai nơi
cùng nhảy qua toàn bộ file và cùng in ra "0 câu" - đúng bằng câu "file
của tôi rỗng". Vòng này gom cách đọc về `csv_utils.read_keyed_csv`
(đặt ở module riêng vì `train_nlu` import `dataset`, đặt helper vào một
trong hai sẽ tạo vòng import) và cho cả hai nơi dùng chung - sửa một bên
thì bên kia không bị bỏ sót. Nhánh báo lỗi file Notepad kiểu Windows 7
(lưu ANSI) được giữ nguyên.

**Trợ lý sửa lỗi gõ đang phá câu người dùng gõ đúng.** `smart_normalize` là cửa
vào của cả tầng NLU, nên mọi câu nói đều đi qua nó. Nhánh "sửa lỗi gõ nhẹ bằng
fuzzy" bản cũ áp cho **mọi** từ dài ≥4 ký tự, kể cả từ người dùng đã gõ CÓ DẤU
đúng. Đo trên 41 từ thông dụng: **12 từ bị đổi thành một từ khác**, trong đó có
từ mất hẳn âm tiết:

    "chơi" -> "cho"    "nhanh" -> "nhân"   "chậm" -> "cảm"   "giấy" -> "giá"
    "thường" -> "trường"   "trưởng" -> "trường"   "tiền" -> "thiền"

Nguyên nhân: `difflib` so độ tương đồng, nên từ 4 ký tự và từ 3 ký tự chung 3 ký
tự vẫn đạt 2*3/7 = 0.86 > 0.82. Cắt/thêm một nguyên âm tiết vẫn "giống nhau"
theo thang đo đó. Nay chỉ sửa nhánh này khi từ **không dấu** - người gõ dấu là cố
ý, nên gần đúng với một từ khác nhiều khả năng là từ khác thật; còn lỗi gõ thật
(gõ nhanh, STT) đều ra từ không dấu, đúng cái nhánh này sinh ra để sửa. Sửa sai
còn tệ hơn không sửa. Đo lại: còn 3/41, và tính năng sửa lỗi vẫn chạy
(`chorme`->`chrome`, `notpadd`->`notepad`).

**Nội dung nhắc nhở dính dấu nối thời gian ở cuối.** Người Việt đặt mốc giờ
SAU nội dung - "nhắc tôi uống nước **sau** 10 phút" - nên sau khi bóc mốc giờ thì
chữ nối bị bỏ lại, và trợ lý đọc thành "Đến giờ rồi. Nhắc bạn: uống nước sau".
Biểu thức cũ chỉ bắt đầu câu nên không bắt được dạng này. Nay gỡ phần dính đuôi
(`sau`/`trước`/`trong`/`vào`/`nữa`/`khi`) khi nó là từ cuối cùng - nên câu hợp lệ
"nhắc tôi đi mua đồ trước khi về nhà" còn nguyên.

**Hạn chế đã biết, cố ý không sửa.** `ACCENT_MAP` có 75 khoá không dấu mà 2 từ có
dấu cùng gốc ("nhac" -> `nhắc` hay `nhạc`; "can" -> `cần` hay `căn`). Đây là mơ
hồ bản thân của việc phục hồi dấu, không phải lỗi code: đo thử quy tắc ưu tiên
từ có tần suất cao nhất trong dataset thì cải thiện **0/75** khoá - lựa chọn
hiện tại đã là tốt nhất theo dữ liệu sẵn có. Cần từ điển tần suất thật mới giải
được; đụng vào đây chỉ là đoán mò.

**Trèo khỏi thư mục dữ liệu.** `data_path("/etc/hosts")` và
`voice_cache/index.csv` trỏ ra ngoài thư mục cache rồi bị phát - nay cả hai kiểm
tra chứa trong thư mục gốc. `predict_proba` nhận hàng xác suất rỗng (file .pkl bị
sửa tay) nổ `ValueError: max() arg is an empty sequence` giết cả câu lệnh.

**Không đổi.** Không API nào bị bỏ; mọi câu hợp lệ cho kết quả y hệt; các chuỗi
báo cho người dùng trong luồng hợp lệ giữ nguyên từng byte.

**Kiểm chứng (đo, không ước lượng).** 644 test trên CẢ HAI đường: `pytest -q` →
`644 passed`; `python run_tests.py -q` trên máy không pytest → `644 pass, 0 fail,
0 skip`; `ruff check` 0; `mypy` 0 lỗi (45 file). Vì CI chưa từng chạy được trên
repo này, tương thích Python 3.9 được tự quét bằng AST trên toàn bộ module,
và `python -m build` xác nhận `csv_utils.py` có thật trong wheel. Toán học kiểm cả 10 cặp câu có
dấu/không dấu cho cùng kết quả, và `--once` chạy thật trên 9 câu: `15 + 27` → 42,
`2,5 nhân 4` → 10.0, `1.234,5 chia 3` → 411.5, `1.234 + 5` → 1239.


## v7.7 (2026-09-20) - Bốn hàm chưa ai audit: cùng một họ lỗi kiểu: 518 test

v7.5-v7.6 audit các điểm vào công cộng (CLI, config, TTS, runner). Vòng này soi
những hàm **chưa** bị chạm tới, bằng cách đưa vào kiểu sai - số, `None`, bytes,
dict rỗng - thay vì chỉ chuỗi. Cả bốn lỗi tìm được đều ở biên kiểu, không phải
thuật toán; cả bốn đều nằm trên đường mà tài liệu đã mời người dùng tự gọi.

**`lite_model`: một chuỗi là MỘT CÂU, không phải một batch ký tự.** `predict`,
`predict_proba`, `score` khai `texts: list[str]` nhưng lặp thẳng
`for text in texts`, nên `predict_proba("mở youtube")` trả về **11 hàng** dự đoán
trông rất hợp lệ cho 11 chữ cái - người gọi không hề được báo. Im lặng trả kết quả
sai còn tệ hơn `TypeError: 'int' object is not iterable` mà `predict(123)` gây ra.
Nay có `_as_texts()`: chuỗi trần → `[chuỗi]`, `None` → `[]`, list/tuple/generator
đi đường cũ (kết quả của tầng NLU/CLI không đổi một byte nào), phần tử lạc kiểu bị ép
qua `as_text`, kiểu không lặp được → `TypeError` nêu đúng tên tham số.
`from_state` cũng kiểm kiểu dict trạng thái: field sai kiểu bị bỏ qua để ra model
"trắng" cho `get_lite_model` huấn luyện lại, thay vì `AttributeError` giữa lúc khởi
động - tình huống thật là file model bị viết dở vì mất điện.

**`executor.cancel_reminder`.** `strip_diacritics((keyword or "").strip())` nổ
`AttributeError: 'int' object has no attribute 'strip'` với keyword kiểu số, và
đường đó là cách duy nhất để xoá một lịch đặt sai. Nay keyword đi qua `as_text`
rồi mới so; `None`/chuỗi rỗng vẫn nghĩa cũ (huỷ tất cả), `id` vẫn huỷ đúng một mục,
và sau khi huỷ `reminders.json` không còn giữ mục đã huỷ.

**`nlu_advanced`: dạy, hỏi lại, và file học.** `teach(text, intent)` gọi
`(intent or "").strip()` → `teach("a", 123)` sập; `confirm_message` index thẳng
`result["intent"]`/`result["target"]` → `confirm_message({})` trả `KeyError` cho
người dùng thay vì một câu hỏi. Nay: ép kiểu qua `as_text`, thiếu `intent` thì hỏi
chung "Bạn muốn tôi làm việc đó phải không? (có/không)" (không in "None"), câu hỏi
cho kết quả hợp lệ **giữ nguyên từng byte**. `log_feedback(..., confidence=None)`
từng hỏng ngay bước `round(float(...))` - mà `feedback.csv` là ĐẦU VÀO của
`train_nlu.py` lần sau, nên một dòng hỏng kéo theo cả vòng huấn luyện; giá trị đọc
không được nay thành `0.0`.

**`config.save_config`.** `save_config({"x": {1, 2}})` để `json` ném
`TypeError: Object of type set is not JSON serializable` từ `encoder.py`, **sau khi
file tạm đã tạo xong**. Nay thử nối JSON trước: báo cùng lý do nhưng chỉ ra ngay
đầu vào sai, và không để lại file tạm/file mồ côi. `save_config("str")` →
`TypeError: save_config cần dict, nhận được str.`

**Không đổi.** Không API nào bị bỏ; `predict`/`predict_proba`/`score` với danh sách
cho kết quả y hệt (test parity); chuỗi báo cho người dùng trong các luồng hợp lệ giữ
nguyên.

**Kiểm chứng (đo, không ước lượng).** 518 test trên CẢ HAI đường: `pytest -q` →
`518 passed`; `python run_tests.py -q` trên máy không pytest → `518 pass, 0 fail,
0 skip`; `ruff check` 0; `mypy` 0 lỗi (43 file); parity batch từng câu
`predict_proba(list) == [predict_proba([t])[0] ...]` trên 3 câu thật.

**Sửa muộn (cùng ngày): một test phụ thuộc môi trường máy.**
`test_adopt_shipped_data_is_noop_for_source_checkout` giả định `VI_ASSISTANT_HOME`
không được đặt; ai làm theo hướng dẫn (đặt biến này trong shell) rồi chạy test từ
source thấy 1 fail dù code đúng - và lần chạy thứ hai lại xanh vì file đã được chép
(đúng hành vi "chép một lần"). Test nay tự xoá biến trước khi đo, và có thêm test
đo chiều ngược lại: có biến → chép `config.json` ĐÚNG MỘT LẦN, không ghi đè file
người dùng. Không đổi code sản phẩm. 518 test.


## v7.6 (2026-09-20) - Kho giọng có lệnh tạo; nhắc nhở chịu được thời điểm thật: 487 test

**Lệnh mới, đóng một khoảng trống để từ v6.** `voice_cache/` chỉ có CHIỀU ĐỌC:
tài liệu bảo "đặt mp3 vào <thư mục dữ liệu>/voice_cache rồi ghi `index.csv`", nhưng
công cụ tạo (`train_tts.py cache`) đã bị bỏ nên người dùng không có cách nào ngoài
viết tay. v7.6 thêm `tts.prewarm()` + CLI:

    python -m vi_voice_assistant.tts --cache --text "mở youtube" --text "tắt máy"
    python -m vi_voice_assistant.tts --cache --file cau_thuong_dung.txt [--engine gtts] [--dry-run]
    python -m vi_voice_assistant.tts --list        # xem kho hiện có gì

- Writers: gTTS (mp3, cần mạng), espeak-ng (wav, offline), pyttsx3 (wav), piper
  (wav), `say` (macOS). Không thêm dependency - thiếu thứ nào thì writer đó
  không xuất hiện, module vẫn import bằng thuần stdlib.
- `available_writers()` khác `available_engines()`: engine biết PHÁT không chắc
  biết GHI RA FILE; `vi-doctor` bây giờ in dòng `[i]` nói đúng điều đó + lệnh cần
  chạy (nhãn mới `[i]` KHÔNG bị đếm vào cảnh báo - có test buộc hai con số khớp).
- `_file_written()` chặn "thành công giả": file WAV 44 byte (chỉ header) bị tính
  là lỗi và bị xoá, thay vì vào cache rồi phát ra im lặng.
- Khoá cache dùng CHUNG một hàm `_cache_key()` cho cả ghi lẫn đọc, có gộp khoảng
  trắng: trước bản này `"Mở  YouTube"` (hai dấu cách) tìm hổng cache dù file đã
  tồn tại.
- `TTSWriteError` mang LÝ DO (chưa cài gì / cần mạng / file rỗng) lên tới CLI,
  nên "[fail]" không còn là một từ vô nghĩa.
- `paths.atomic_write_text()`: `index.csv` ghi theo cùng kiểu an toàn như JSON
  (file tạm + fsync + rename), và `atomic_write_json()` gọi qua nó - một chỗ ghi
  đĩa duy nhất, không còn hai bản sao thủ tục.

**Nhắc nhở (`executor`).** `action_set_reminder` đọc `data["time"]` rồi gọi thẳng
`.get("type")`: một model (hay file `--json` người dùng tự viết) gửi
`"time": "3 phút nữa"` làm cả lệnh chết bằng `AttributeError: 'str' object has no
attribute 'get'`. Nay `time` chuỗi/số được đưa qua `parse_time_expression`, số
trần hiểu là phút, và `minutes`/`hour`/`minute`/`day_offset` kiểu rác/NaN/vô hạn đi
qua `_to_number()` (mặc định + chặn biên) thay vì nổ `float()`/`int()`.
- Trợ lý hỏi "Bạn muốn tôi nhắc vào lúc nào ạ?" rồi người dùng đáp "5 phút nữa"
  THÌ TRƯỚC ĐÂY câu trả lời bị phân tích như lệnh MỚI: lời nhắc mất nội dung, đặt
  thành "báo thức". Nay lời nhắc chờ 5 phút (`PENDING_REMINDER_TTL`), REPL nối thời
  điểm vào đúng việc đang hẹn; câu không chứa thời điểm thì trả lại cho NLU và xoá
  chờ; `quên`/`reset` xoá luôn phần chờ; `--dry-run` in `[TEST] Sẽ nhắc ...` và
  KHÔNG đặt lịch.

**`config.update_config`.** `update_config("tts")` từng nổ `'str' object has no attribute 'items'`;
nay báo `TypeError: update_config cần dict, nhận được str: '...'`. `_deep_merge`
copy giá trị dict, hết cảnh config trong bộ nhớ bị đổi khi người gọi sửa `updates`.

**Runner nhúng (`run_tests.py`) - hai lệch hợp đồng với pytest thật.**
- `raises` trả về thẳng exception: test viết `e.value`/`e.match()` theo pytest đỏ
  trên runner mà xanh trên máy có pytest. Nay có `_ExceptionInfo`
  (`.value`/`.type`/`.match()`) cho CẢ HAI dạng gọi; `match()` khớp → `True`, lệch
  → `AssertionError` (đúng pytest 9, không phải `False`).
- `-k` chỉ so với TÊN HÀM, còn pytest so với nodeid: `run_tests.py -k v76` chạy 0
  test rồi báo "0 fail" = màu xanh giả. Nay `-k` hiểu `file.py::test_x` +
  `and/or/not`, và nếu không test nào khớp thì exit 1 kèm cách kiểm tra.
- Sửa lây nhiễm trạng thái làm test đổi kết quả theo thứ tự chạy:
  `tts.set_enabled(False)` trong `finally` (v7.5) và `executor.SPEAK_ENABLED = False`
  (v6) để lại trạng thái cho MỌI file chạy sau; chuyển sang `monkeypatch` để tự
  phục hồi. Test mới cũng chặn timer thật của lịch nhắc để không nổ giữa phiên.

**Kiểm chứng (đo, không ước lượng).** 487 test trên CẢ HAI đường: `pytest -q` →
`487 passed`; `python run_tests.py -q` trên máy không pytest → `487 pass, 0 fail,
0 skip`; parity `-k v76` → 94 test trên pytest và 94 trên runner; `ruff check` 0,
`mypy` 0 lỗi (42 file); vòng tròn cache đo thật: `prewarm` → `speak()` phát file
cache, không gọi engine; CLI báo đúng khi máy không có writer.

## v7.5 (2026-09-20) - Điểm vào công cộng chịu được dữ liệu thật: 392 test

### Vì sao bản này tồn tại
Bốn bản trước sửa lỗi ở tầng dữ liệu và tầng cài đặt; bản này quét một lớp hẹp hơn
mà chỉ ra được khi chạy thật: **hàm ký mong `str`, còn giá trị thật đến từ file JSON
hoặc từ người gọi khác lại là số/`None`/danh sách**, và **một file hỏng không được
phép làm chết mọi lệnh**. Bảy lỗi dưới đây đều được tìm bằng cách cho chạy, không
phải đọc mã.

### Lỗi thật đã sửa
1. **`config.json` hỏng giết cả ứng dụng** - `executor` nạp config ngay lúc `import`,
   nên một file thiếu dấu phẩy (hoặc được lưu thành JSON `[...]`) làm MỌI lệnh chết
   bằng traceback, **kể cả `--doctor`** - thứ duy nhất có thể chỉ chỗ hỏng. Thêm
   `config.load_config_safe()`: trả `(giá trị mặc định, mô tả lỗi)`; `executor` lưu
   `CONFIG_ERROR`, `main` in cảnh báo một dòng kèm đường dẫn cần sửa, các lệnh vẫn
   chạy. `load_config()` **vẫn raise** cho người gọi chủ động (lệnh "nạp lại",
   `install.py --check`).
2. **`tts.speak()`** - hai lỗi cùng một dòng: `text.strip()` crash khi nhận
   `123`/`None`/danh sách, và câu `safe_print` chạy TRƯỚC kiểm tra nên câu rỗng vẫn
   in `"[TRỢ LÝ] None"` - màn hình báo trợ lý vừa nói "None" trong khi nó không nói
   gì. Nay kiểm tra nội dung trước, im lặng tuyệt đối với câu rỗng.
3. **`nlu_advanced.understand("")` bịa ra một lệnh** - `"   "` đi hết tầng phân loại
   và trả `{'intent': 'open_website', 'target': 'unknown'}`. `run_once`, `--json` và
   mọi script "lặp qua kết quả rồi thực thi" vì thế đi mở thật một website tên
   `unknown`. Hợp đồng mới: không có nội dung -> `[]`.
4. **`--once ""` rơi vào REPL** - `args.once or args.text` không phân biệt "được đưa
   mà rỗng" với "không được đưa", nên câu rỗng bị bỏ qua im lặng và lệnh một-cau
   không bao giờ thoát (treo trong script/CI). Thêm `_one_shot_text()`: in
   "Câu rỗng - không có gì để thực hiện." rồi thoát 0.
5. **Kiểu ở tầng NLU/NLP** - `intent_model.predict_intent(123)` crash ở
   `_EntityContext.build` (`(text or "").strip()`) *sau khi* `normalize_text` đã ép
   kiểu tử tế; `split_commands(123)`/`replace_number_words(123)` chết bằng
   `TypeError: expected string or bytes-like object, got 'int'` - câu lỗi không chỉ
   chỗ nên sửa. `text_utils._as_text` được công khai thành **`as_text`** và dùng ở cả
   ba điểm vào.
6. **`sanitize_filename()` thiếu ba thứ** (tên file ở đây đến từ nội dung người
   dùng): (a) cùng lỗi kiểu trên; (b) **tên dành riêng của Windows** - `CON`, `PRN`,
   `AUX`, `NUL`, `COM1-9`, `LPT1-9` bị OS từ chối ở mọi vị trí kể cả có phần mở rộng,
   ghi vào là treo/lỗi khó hiểu; (c) **giới hạn 255 byte cho một thành phần đường
   dẫn** - tiếng Việt ~3 byte/ký tự nên cái tên 90 ký tự đã thành `OSError
   [Errno 36]`. Nay chặn tên dành riêng bằng `_`, cắt theo byte rồi giải mã (không
   cắt giữa ký tự), và hàm idempotent.
7. **`dataset.get_dataframe()`** báo `ModuleNotFoundError: No module named 'pandas'`
   rồi thôi; nay nói luôn `pip install pandas` hoặc dùng `get_dataset_as_lists()`.
8. **`raises(E, fn)` trong runner nhúng là một cái bẫy** - shim chỉ là
   `@contextmanager`, nên dạng gọi *thẳng* trả về generator và `fn` **không bao giờ
   được gọi**: test báo PASS dù chẳng kiểm tra gì. Nay `_raises` hỗ trợ cả hai dạng
   (gọi `fn`, bắt đúng kiểu, `match` là regex thật, lỗi sai kiểu để nguyên bay lên),
   và shim có thêm `importorskip` (thiếu module -> SKIP, không phải fail).
9. **`@pytest.mark.parametrize("x", [])` từng là màu xanh giả** - vòng sinh case
   chạy 0 lần, test biến "không có gì để kiểm tra" thành PASS. Runner nhúng giờ đánh
   dấu một thất bại có tên `[empty-parametrize]` (exit 1).

### Test
`tests/test_v75_input_hardening.py` (18) + `tests/test_v75_runner_shim.py` (7) ->
**392 test**, chạy được bằng cả pytest lẫn runner nhúng (đã đo cả trên venv
KHÔNG có pytest). Mỗi lỗi ở trên có ít nhất một test; riêng lỗi 1 và 4 được test
bằng cách chạy `main.py` thật trong `VI_ASSISTANT_HOME` tạm - lỗi nằm ở đường
import/CLI nên unit test trong cùng tiến trình không thấy được.

Test cuối của nhóm shim là **rào cho tương lai**: nó quét mọi `pytest.X` mà các
file test đang dùng và bắt shim phải có đủ X. Thiếu một cái là máy chưa cài pytest
chết ngay, còn máy có pytest thì vẫn xanh - kiểu lệch lạc khó tự phát hiện nhất.

## v7.4 (2026-09-20) - Toàn vẹn dữ liệu & kiểu: mypy 60 lỗi -> 0, 367 test

### Vì sao bản này tồn tại
v7.3 làm cho dự án **cài được**. Bản này trả hai món nợ mà các bản trước để lại:
(1) `[tool.mypy]` có sẵn trong pyproject nhưng **chưa từng được chạy** - bật lên
thấy ngay 60 lỗi, trong đó có một lỗi làm `vi-doctor` sập; (2) file dữ liệu của
người dùng vẫn được ghi theo kiểu "mở ra là mất nội dung cũ". Xen giữa là một lỗi
làm **toàn bộ trợ lý chết trên Python 3.9** - bản mà README và CI đều nói hỗ trợ.

### Lỗi thật đã sửa
1. **`import intent_model` chết trên Python 3.9** [CRITICAL]
   `str | None` trong chữ ký hàm (PEP 604) cần Python 3.10, còn `intent_model.py`
   và `nlu_advanced.py` KHÔNG có `from __future__ import annotations`. Trên 3.9:
   `TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'` ngay lúc
   import, tức mọi tính năng chết chứ không riêng gì máy học. CI có job 3.9 nhưng
   workflow chưa nằm trên nhánh mặc định nên chưa lần nào chạy; lỗi sống dai từ
   v7.1. Sửa: thêm future import (hành vi trên 3.10+ giữ nguyên) + máy quét AST
   trong `tests/test_v74_compat.py` khoá lại - quét cả `tests/` vì test cũng phải
   chạy trên 3.9 (chính file test mới này từng vi phạm đúng rule nó kiểm).
2. **`import train_phobert` tự chạy... vòng huấn luyện** [HIGH]
   `main()` nằm NGOÀI khối `if __name__ == "__main__":` (lệch đúng một cấp thụt
   lề), nên IDE/pytest/bộ kiểm tra import nào chạm vào là bị kéo qua toàn bộ
   pipeline; nặng hơn `parse_args()` đọc argv của chương trình gọi nên tiến trình
   nhận `SystemExit(2)` không lời giải thích. Nay `main(argv=None) -> int` và chỉ
   gọi trong khối guard - đúng khuôn `train_nlu`/`run_tests` đã sửa ở v7.3.
3. **`vi-doctor` chết trước khi in nổi một dòng trên Python >= 3.14**
   `platform.major` không tồn tại (phải là `sys.version_info.major`), và nó nằm ở
   nhánh chỉ chạy khi Python *mới hơn* bản đã kiểm tra - đúng chỗ không ai test.
   Quan trọng hơn: mỗi mục báo cáo giờ đi qua `_section_result()`, nên một mục
   hỏng (file model đọc không được, quyền thư mục...) thành dòng `[X]` chứ không
   kéo sập cả báo cáo, và CLI không bao giờ ném traceback cho người dùng.
4. **Báo cáo tự mâu thuẫn**: `print_report` in "Mọi thứ ổn - chạy: python main.py"
   mỗi lần không có lệnh gợi ý nào - kể cả khi còn mục `[X]` và exit code là 1.
5. **Dispatcher chọn cách gọi handler bằng bảng GHI TAY** (`_HANDLERS_WITH_DATA`):
   thêm handler 2 tham số mà quên ghi tên vào bảng thì gọi `handler(target)` ->
   TypeError. Nay suy ra từ `inspect.signature` (bọc `lru_cache`); tên cũ vẫn còn
   nhưng là giá trị TÍNH RA nên không lệch được nữa.
6. **`target` không phải chuỗi làm sập dispatcher**: `(2026 or "").strip()` ->
   AttributeError. Nay ép kiểu TRƯỚC khi strip; `intent` không phải chuỗi thì báo
   "không hiểu ý định" thay vì lỗi dict.
7. **Mục map lệch kiểu trong config.json lọt qua im lặng**:
   `CONFIG.get("app_map_linux", {})` trả nguyên giá trị, nên `"app_map_linux": null`
   hoặc nhầm sang chuỗi nổ ở `subprocess` - nơi người dùng chỉ thấy traceback. Nay
   `_as_map()` trả dict rỗng + ghi log, rơi vào nhánh "chưa cấu hình" đã có sẵn
   hướng dẫn sửa đúng tên key.
8. **`giong_nc`: file JSON đồng ý giấy phép hỏng làm sập CLI** - `json.load` trả gì
   trả; nay chỉ chấp nhận dict.
9. **`monkeypatch.setenv` của runner nhúng không hoàn tác được**: `os.environ` không
   phải dict, `undo()` gọi `delattr` rồi im lặng bỏ qua -> biến môi trường đặt ở
   test trước RÒ sang mọi test chạy sau (kết quả phụ thuộc thứ tự). Thêm `delenv`
   (pytest có, shim thiếu) và đánh dấu bản ghi kiểu "item" để undo dùng đúng phép.

12. **`voice_cache/` vẫn nằm trong site-packages** - chỗ cuối cùng chưa theo
    `paths.py` (bản v7.3 đã chuyển config/model/log/history nhưng quên kho giọng).
    Hệ quả: bản cài bằng pip bắt người dùng nhét mp3 vào thư mục thường CHỈ ĐỌC và
    bị xoá khi nâng cấp. Nay `VOICE_CACHE_DIR = data_path("voice_cache")`, và
    thư mục cũ cạnh mã nguồn vẫn được ĐỌC tiếp (ai đã có cache từ bản 6.x không
    mất gì). Cùng lúc, `_load_voice_cache()` chỉ nhận file thật sự tồn tại - trước
    đây một dòng lệch trong `index.csv` đưa Path ảo vào bảng tra, tts thử "phát"
    file không có.

### Toàn vẹn dữ liệu (thay đổi chính)
`paths.atomic_write_json()` - MỘT hàm duy nhất: file tạm cùng thư mục -> flush +
`fsync` -> `os.replace` -> `fsync` thư mục -> dọn file tạm khi lỗi. Ba nơi trước
đây tự viết ba biến thể, nay dùng chung:
- `config.save_config`: đã có fsync, giữ nguyên hành vi;
- `executor._save_reminders`: thiếu fsync và **thiếu tạo thư mục cha** - khi
  `REMINDERS_PATH` trỏ vào thư mục chưa tồn tại thì `mkstemp` raise và `except
  OSError` nuốt mất, nhắc nhở biến mất không một lời báo;
- `main.save_history_entry`: nặng nhất - `open("w")` cắt file ngay, tiến trình
  chết giữa chừng (Ctrl+C, hết đĩa, mất điện) để lại `.history.json` rỗng.
Chi phí đo được: **0,25 ms -> 1,39 ms mỗi lần lưu** (100 lần, trên tmpfs). History
chỉ ghi một lần mỗi lệnh nên không cảm nhận nổi; đổi lại là không mất dữ liệu.

### Kiểu được kiểm tra thật
- `[tool.mypy]` bật đủ độ: `check_untyped_defs`, `no_implicit_optional`,
  `warn_redundant_casts`, `warn_unused_ignores`, `files` gồm cả `install.py`.
  `python_version` phải đẩy lên 3.10 vì mypy không còn phân tích cho 3.9 - việc
  chạy *thật* trên 3.9 do job `test` (ma trận 3.9-3.13) và `test_v74_compat.py` lo.
- **60 lỗi -> 0** trên 37 file nguồn (kể cả test). `tests/` được nới lỏng có ghi
  rõ lý do trong pyproject: `lambda p: opened.append(p) or True` là phong cách test
  hợp lệ, siết ở đó chỉ sinh noise chứ không bắt thêm bug của người dùng.
- CI thêm job `typecheck` (mypy pinned) -> tổng cộng **7 job**.

### Cài đặt thông minh hơn
`install.py` từng khuyên người ĐANG ở trong venv... đi tạo venv, và thử `--user` /
`--break-system-packages` - hai cờ mà pip từ chối trong venv -> một lần lỗi vô ích
rồi vẫn tắc. Nay `in_virtualenv()` (VIRTUAL_ENV / CONDA_PREFIX / sys.prefix) quyết
định hướng: trong venv thì không đổi cờ, in hướng dẫn đúng (`python -m pip
--version`, venv nằm trên đĩa chỉ đọc thì tạo lại ở nơi khác). `retry_flags_for`
nhận `in_venv` như tham số THUẦN để test được mọi nhánh trên mọi máy.

### Runner nhúng: hai chỗ tự nói dối
10. **Chạy `run_tests.py` trên bản cài bằng pip in ra "0 pass, 0 fail" với exit 0** -
    wheel cố ý không kèm `tests/`, nên lệnh đó không kiểm tra gì mà vẫn xanh. Cùng
    họ với `|| echo passed` từng có trong CI. Nay: không thấy file test nào thì in
    rõ nguyên nhân + đường dẫn đã tìm, và trả **exit 1**.
11. **Không có cách nào test chính runner nhúng trên máy CÓ pytest** - mọi lệnh
    `run_tests.py` đều bị đẩy sang pytest thật, nên phần shim (fixture,
    parametrize, caplog, monkeypatch...) nằm ngoài vùng kiểm tra, hỏng cũng
    không ai biết. Thêm `VI_TESTS_FORCE_EMBEDDED=1` để cưỡng chế runner nhúng;
    job `embedded-runner` trong CI giờ cài pytest rồi *vẫn* chạy runner nhúng,
    nên phần đó được kiểm tra bất kể image của runner đổi ra sao.

### Tài liệu
`HUONG_DAN_SU_DUNG.txt` có mục mới về **định dạng thật của `voice_cache/index.csv`**
kèm đoạn Python thuần để sinh chỉ mục - vì `tts.py` chỉ ĐỌC kho giọng mà dự án
không còn công cụ tạo nó (lệnh `train_tts.py cache` đã bị bỏ từ trước, nên tài liệu
cũ đang bảo người dùng làm một việc không có cách làm). Đoạn mã trong tài liệu đã
được chạy thật và `tts._load_voice_cache()` đọc ra đúng mục.

### Test
`tests/test_v74_hardening.py` (29) + `tests/test_v74_compat.py` (8) -> **367 test**,
xanh trên cả ba cách chạy: pytest, `python vi_voice_assistant/run_tests.py` từ gốc,
và `python run_tests.py` từ trong package trên máy chưa cài pytest.

## v7.3 (2026-09-20) - Cài đặt & tiện nghi: `pip install .` chạy ĐƯỢC, 330 test

### Vì sao bản này tồn tại
v7.2 dọn code nhưng KHÔNG ai kiểm tra xem dự án **sau khi cài đặt** còn chạy
được không. Vừa kiểm tra là thấy nó chết ngay. Bản này nhắm đúng ba chỗ:
cài đặt, dùng hằng ngày, và tốc độ.

### Lỗi nghiêm trọng đã sửa (cài đặt / đóng gói)
1. **`pip install .` tạo ra gói DÙNG KHÔNG ĐƯỢC** [CRITICAL]
   - Triệu chứng: `vi-assistant` chết bằng
     `ModuleNotFoundError: No module named 'platform_utils'`.
   - Nguyên nhân: wheel chứa đủ file `.py` nhưng package không có `__init__.py`,
     mà toàn bộ mã nguồn dùng import PHẲNG (thiết kế "chạy thẳng từ thư mục").
   - Sửa: thêm `vi_voice_assistant/__init__.py` (nối thư mục gói vào `sys.path`
     MỘT LẦN, không sửa 20 file import) + `__main__.py` cho
     `python -m vi_voice_assistant`; khai báo tường minh `packages` +
     `package-data` trong pyproject.
2. **Dữ liệu người dùng bị ghi vào `site-packages`**
   - `config.json`/`reminders.json`/`feedback.csv`/`logs/`/model `.pkl` đều lấy
     `Path(__file__).parent` làm chỗ lưu -> máy cài system-wide (read-only) thì
     `PermissionError` giữa phiên, và MỌI dữ liệu bị xoá khi nâng cấp gói.
   - Sửa: module `paths.py` mới, quy tắc
     `$VI_ASSISTANT_HOME` → thư mục source (nếu ghi được) →
     `%LOCALAPPDATA%` / `~/Library/Application Support` / `$XDG_DATA_HOME`;
     thư mục không tạo được thì rơi về temp dir có PID (KHÔNG bao giờ crash).
3. **File riêng tư của người build bị phát tán trong wheel**
   - `include-package-data = true` khiến setuptools vơ cả file đang có trên đĩa
     (`.history.json` - tức NHỮNG CÂU ĐÃ NÓI với trợ lý) vào wheel.
   - Sửa: `include-package-data = false` + `package-data` liệt kê đích danh
     6 file cần thiết; thêm bước CI kiểm wheel không có file runtime/tests.
4. **`config.json` không đi theo wheel** -> bản đã cài chạy với cấu hình mặc định
   trong code, mất whitelist. Nay `paths.migrate_from_package_dir()` chép một lần
   (không bao giờ ghi đè) dữ liệu từ gói sang thư mục người dùng.
5. **`python run_tests.py -q` chết trên máy chưa cài pytest**: runner tự định nghĩa
   argparse nhưng không có cờ `-q` -> `unrecognized arguments`, trong khi CI
   `no-deps` và `install.py` chính xác là gọi như vậy. Nay nhận `-q` thật và bỏ
   qua cờ lạ (`parse_known_args`).
6. **Runner nhúng thiếu 4 khả năng của pytest** - mỗi cái đều biến test HỢP LỆ
   thành lỗi trên máy chưa cài pytest:
   - fixture-nhà-fixture (`def fx(tmp_path, monkeypatch)`) -> TypeError;
   - fixture `yield` -> test nhận generator, teardown không chạy;
   - thiếu `caplog` -> missing argument;
   - `monkeypatch.setattr(..., raising=False)` -> TypeError;
   - `parametrize` một tham số là LIST bị bung thành TỪNG KÝ TỰ
     (`main.py: error: unrecognized arguments: - h i s t o r y`).
   Thêm: `__spec__` cho module giả (nếu không, `import pytest` chết bằng
   `pytest.__spec__ is None`), và `_detect_real_pytest()` để shim không tự nhận
   mình là pytest thật ở lần import thứ hai.
7. **`import run_tests` giữa một phiên pytest che mất pytest thật** (gán
   `sys.modules["pytest"]` vô điều kiện) -> fixture/mark của các file chạy sau
   hỏng khó hiểu. Nay chỉ lắp shim khi KHÔNG có pytest thật.
8. **Test của v7.3 tụt ở chế độ nhúng** (chỉ copy thư mục con rồi chạy,
   không cài gì): hai test import theo tên package nên cần thư mục gốc trên đường
   dẫn import. File test tự thêm gốc vào `sys.path`; bây giờ bộ test xanh ở cả ba cách
   chạy: `pytest`, `python vi_voice_assistant/run_tests.py` từ gốc, và
   `python run_tests.py` từ bên trong package không cần `PYTHONPATH`.

### Tiện lợi (CLI)
- **Nói thẳng ra lệnh, không cần cờ**: `vi-assistant "mở youtube"` (thay vì
  bắt nhớ `--once`); `--once` vẫn giữ nguyên.
- **`--yes` / `-y`**: bỏ bước xác nhận cho script/CI; `_confirm()` khi không có
  bàn phím tương tác nay nói rõ NGUYÊN NHÂN + chỉ cách khắc phục, thay vì "[HỦY]"
  lạnh lùng.
- **`--doctor` (và `vi-doctor`)**: chẩn đoán cài đặt trong một lần chạy -
  Python, nền tảng, đang chạy source hay pip, thư mục dữ liệu có ghi được không,
  config hợp lệ + đếm whitelist THẬT theo nền tảng, model đã cache/fingerprint còn
  hợp không, từng thư viện tuỳ chọn, engine TTS, giọng AI - và in ĐÚNG lệnh cần gõ
  (đã khử trùng lặp). Có `--json` cho công cụ.
- **Phím ↑/↓ gọi lại lệnh cũ + Tab hoàn thành tên lệnh** trong REPL (dùng
  `readline` nếu có, nhập history từ `.history.json` sẵn có; không có readline
  thì REPL y hệt trước - nâng cấp tuỳ chọn, không phải yêu cầu mới).
- **Gợi ý khi gõ sai lệnh**: `he thogng` -> "Có phải bạn muốn gõ  he thong ?".
  Bảng gợi ý lấy trực tiếp từ table đăng ký lệnh, nên thêm lệnh mới tự được gợi ý.
  An toàn: KHÔNG BAO GIỜ gợi ý lệnh thoát (`hát` không còn bị xui "thoát"), và
  chỉ áp cho câu <= 2 từ.
- Console scripts mới: `vi-doctor`, `vi-train`, `vi-voice`; `train_nlu`/`run_tests`
  có `main()` trả mã exit thật + `--lite` (huấn luyện model không cần sklearn).
- `install.py` ở thư mục gốc: cài đặt một lệnh, chỉ dùng stdlib -
  `--check`, `--profile core|ml|voice|full|all|dev`, `--offline`, `--dry-run`,
  `--index-url`; tự xử lý PEP 668 theo trình tự an toàn
  (`--user` trước, `--break-system-packages` chỉ khi hết cách) và nhắc tạo venv
  bằng đúng cú pháp của nền tảng đang chạy.

### Hiệu năng
- `text_utils.normalize_text()` / `strip_diacritics()` có cache LRU 8192 câu:
  tầng NLU gọi lại cùng một chuỗi hàng chục lần cho MỘT câu nói.
  Đo: 3.4µs -> **0.32µs** mỗi lần lặp lại; `predict_intent` 172µs -> **140µs**/câu.
- Đầu vào không phải chuỗi được ép sang `str` thay vì `AttributeError`.
- Startup đã nhanh sẵn (83ms toàn bộ tiến trình, model lite cache 5ms) nên KHÔNG
  "tối ưu" thêm bằng cách hy sinh độ đọc được của code; con số đo được ghi trong
  test để không ai phải đoán lại.

### Kiểm chứng
- 251 -> **330 test**; `pytest` và `python run_tests.py` (môi trường KHÔNG có
  pytest) đều **330 pass / 0 fail** - xác nhận bằng venv sạch không cài pytest.
- `ruff check .` = 0 (thêm `install.py`, `paths.py`, `diagnostic.py` vào vùng lint).
- Cài thật + chạy thật: `pip install .` trong venv → `vi-assistant --version`,
  `vi-doctor`, `python -m vi_voice_assistant --once ...` từ `cwd` khác;
  chmod read-only thư mục cài đặt vẫn chạy, dữ liệu rơi vào `~/.local/share/...`.
- Wheel mới: 34 file, `__init__.py`/`__main__.py`/`config.json`/`diagnostic.py`
  có mặt; `.history.json`, `*.pkl`, `tests/`, `__pycache__` không có.


## v7.2 (2026-09-13) - Trả nợ kỹ thuật: 347 cảnh báo lint -> 0, 15 lỗi thật đã sửa

### Tổng quan
- Mục tiêu bản này KHÔNG phải tính năng mới: dọn toàn bộ nợ kỹ thuật tích tụ qua
  các bản merge (lint, hàm 20-30 nhánh, code chết, tài liệu nói khác code).
- 347 cảnh báo ruff -> **0**; số test 220 -> **251**; hành vi giữ nguyên có kiểm chứng.

### Lỗi thật đã sửa (mỗi lỗi có test hồi quy trong `tests/test_v72_regressions.py`)
1. **run_tests.py luôn thoát 0** dù có test fail - runner tự viết nuốt mã lỗi, nên
   "220 pass" trên CI có thể là ảo giác. Nay uỷ quyền cho pytest khi có sẵn và trả exit code thật.
2. **train_nlu.py import scikit-learn cứng** - máy chưa cài thư viện ML không chạy
   được dù README quảng cáo "chạy ngay không cần cài gì" -> sklearn/joblib thành tuỳ
   chọn, gọi `_require_sklearn()` ngay trước khi cần.
3. **executor._escape_osascript escape SAI THỨ TỰ** - thay `\"` trước rồi `\`, nên
   backslash vừa chèn bị nhân đôi và nháy kép thoát ra ngoài chuỗi => nội dung nhắc
   nhở do người dùng gõ chạy thành MÃ AppleScript. Đổi thứ tự escape (lỗi bảo mật).
4. **`huy nhac` chỉ xoá trong RAM** - lời nhắc đã huỷ "hồi sinh" ở lần bật máy sau,
   và lời nhắc đang chờ biến mất khi tắt máy. `cancel_reminder` + `_save_reminders`
   Nay ghi đĩa atomic; `restore_reminders` bỏ mục quá hạn (không "nổ" dồn khi mở máy).
5. **ngưỡng tự tin đọc NGOÀI try/except lúc import** (`nlu_advanced`) - một giá trị
   sửa tay sai trong config.json ném ValueError/TypeError ngay `import nlu_advanced`
   và làm chết cả main.py, kể cả phần không liên quan tới ML. Nay: cảnh báo + mặc định an toàn.
6. **lệnh `nap lai` không đổi được ngưỡng** - tầng NLU đóng băng từ lúc import, executor
   mới được nạp lại -> người dùng sửa `confidence_accept` rồi nạp lại vẫn thấy hành vi cũ.
   Thêm `refresh_thresholds()` đồng bộ cả hai phía.
7. **tts: engine chết bị nuốt im lặng / tên engine sai bị hiểu là auto** - `--engine pipper`
   chạy "bình thường" nên không ai biết mình viết sai. Nay ghi log cảnh báo kèm danh sách
   hợp lệ, và chốt lại engine sống được (`_resolved_engine`) khi engine đang dùng hỏng giữa chừng.
8. **stt hard-code 44 byte header WAV** - chỉ đúng với PCM canonical; nếu `wave` ghi
   chunk mở rộng thì dữ liệu âm thanh lệch -> nhận diện sai im lặng. Nay đọc độ dài
   header thật; thiếu sounddevice cũng báo rõ thay vì giả vờ "không nghe thấy gì".
9. **config._validate_config là CODE CHẾT** - hàm tính `missing` rồi `pass`, docstring
   vẫn ghi "raise nếu sai nghiêm trọng". Nay: gọi tên từng khoá thiếu/khoá LẠ (gõ sai
   chính tả), raise sớm khi `website_map`/`app_map_*` sai kiểu (tránh AttributeError
   giữa lệnh), và bỏ mô tả "cache TTL" chưa từng tồn tại.
10. **logging_setup dùng lock giả** (không phải `threading.Lock` thật) -> race khi nhiều
    thread cùng ghi log (bộ đếm lời nhắc + REPL + TTS đều đa luồng).
11. **lite_model / hash md5** - `hashlib.md5(..., usedforsecurity=False)` để chạy được
    trên Python dựng theo FIPS (md5 chỉ dùng làm fingerprint, không dùng bảo mật).
12. **dataset._generate chia cho 0** - người dùng tự sửa `dataset.py` mà để trống một
    danh sách MẪU CÂU thì `% n` (n=0) ném ZeroDivisionError NGAY lúc import `dataset`,
    giết luôn cả trợ lý lẫn toàn bộ test với traceback không liên quan gì tới config.
13. **platform_utils.setup_console không khôi phục encoding cũ** - trạng thái console bị
    đổi vĩnh viễn cho tiến trình con; Nay có cờ revert.
14. **main.py thiếu `--engine nc`** - module `giong_nc.py` đã có sẵn engine "nc" nhưng
    CLI không cho chọn.
15. **CÂU VÔ NGHĨA VẪN ĐƯỢC THỰC THI** - "asdfgh jklzxbv" được model lite chấm tự tin
    0.50, CAO HƠN ngưỡng `CONFIDENCE_ACCEPT` (0.45), nên trợ lý lẽ ra đã gọi hàm thật
    theo một câu hoàn toàn vô nghĩa. Nguyên nhân: softmax với temperature 0.08 khuếch
    đại khoảng cách log-prob, "không có bằng chứng" vẫn thành "tương đối chắc chắn".
    Nay mỗi câu dự đoán phải qua **bảo chứng từ điển** `evidence_ratio()` (tỷ lệ feature
    nằm trong từ điển huấn luyện, char-ngram chỉ tính 25%): câu rác -> 0%, REPL hỏi lại;
    câu tiếng Việt thật -> không đổi. Không cần file model mới (từ điển suy ra từ
    `_log_prob`), và `predict_proba_dict()` vẫn trả phân phối softmax nguyên bản.

### Kiến trúc / chất lượng code
- **347 -> 0 cảnh báo ruff** (E, F, W, C90, I, N, UP, S, B, A, C4, TCH, TID, Q, RUF);
  mỗi dòng `ignore` trong `pyproject.toml` có chú thích lý do + `per-file-ignores`.
- **Tách các hàm quá phức tạp** (C901 > 10) thành bảng tra + hàm một nhiệm vụ, xoá dần
  các chuỗi if/elif theo nền tảng/theo lệnh:
  - `main.main()`: REPL dispatcher -> `_CONTROL_COMMANDS` (từ khoá -> handler) +
    `_CONTROL_PREFIXES` (lệnh có tham số) + `ReplState`/`ReplContext` test được từng lệnh.
  - `executor.action_system_control()`: bảng `COMMANDS_WINDOWS/MACOS/LINUX`,
    `VOLUME_*`, handler riêng theo nền tảng; `None` = "nền tảng này không làm được"
    -> in `[BỎ QUA]` thay vì nói dối "đã thực thi".
  - `intent_model`: `parse_time_expression` (28 nhánh) thành 4 máy phân tích + bảng
    quy tắc đổi giờ theo buổi; `extract_entity` (20 nhánh) thành `_ENTITY_HANDLERS`;
    `_parse_number_run` (25 nhánh) thành bảng quy tắc `_NUMBER_RUN_RULES`.
  - `tts.speak`, `stt.listen_once`, `config._validate_config`, `train_nlu.train`,
    `giong_noi_ai.main` cũng được tách tương tự.
- **Kiểm chứng tương đương hành vi** bằng đối chiếu tự động với bản v7.1 (module cũ nạp
  song song): 70.668 cụm từ-số x 3 hàm, 96.737 câu thời gian, 1.618 câu x 13 intent
  trích xuất thực thể => **0 khác biệt**. Các hàm refactor không đổi hành vi, chỉ đổi cấu trúc.

### Đóng gói & CI
- `dependencies = []`: `pip install .` không còn bắt cài scikit-learn/numpy (chuyển vào
  `[full]`/`[ml]`) - khớp với cam kết "chạy ngay không cần cài gì"; bỏ 2 marker
  `python_version < "3.9"` mâu thuẫn với `requires-python >= 3.9`.
- CI: bỏ bước `pytest ... || python run_tests.py` (dấu `||` biến CI ĐỎ thành XANH);
  mỗi bộ test một bước riêng; thêm bước **ruff**; thêm **Python 3.13** (pyproject đã
  quảng cáo nhưng chưa từng được kiểm tra); thêm job "không cài tuỳ chọn" để giữ hợp
  đồng "chỉ cần stdlib".

### Tests
- 220 -> **251 test**; file mới `tests/test_v72_regressions.py` (31 test) - mỗi test
  gắn với một lỗi ở trên, có chú thích mô tả triệu chứng trước khi sửa.


## v7.0 (2026-09-13) - Nâng cấp toàn diện & fix regression sau merge

### Tổng quan
- Merge 2 bản zip v6.4 (`vi_voice_assistant_v6_4_vieneu.zip` + `out_vi_voice_assistant_v6_4_fixed.zip`) thành một dự án duy nhất
- Fix tất cả lỗi regression, đạt 220/220 tests pass
- Nâng cấp kiến trúc: pyproject.toml, requirements.txt, logging_setup.py, platform_utils.py, config.py

### Fix lỗi nghiêm trọng (regression sau merge)

#### 1. Regex `bad character range \-( at position 11` [CRITICAL]
- **executor.py:92** `_SAFE_PATH_RE = r"^[\w\s:\\/.\\-()%]+$"` → FAIL
  - Fix: `r"^[\w\s:\\/.\-()%]+$"` (escape `-` đúng cách) ✅
- **text_utils.py** `_KEEP_RE = r"[^\w\s\.\-/:\\]"` → FAIL tương tự
  - Fix: `r"[^\w\s./:\\-]+"` (đưa `-` ra cuối) ✅
- **_INVALID_FILENAME_RE** `r'[<>:"/\\|?*\x00-\x1f]'` raw string chứa \x00 không hoạt động
  - Fix: `r'[<>:"/\\|?*]'` + xử lý `ord(c) < 32` riêng ✅

#### 2. Tương thích HOME/REMINDERS_PATH khi monkeypatch bằng str
- `HOME / "Pictures"` fail khi `HOME = str(tmp_path)` trong tests
  - Fix: `Path(HOME) / "Pictures"` + `Path(pictures_dir).mkdir()` ✅
- `REMINDERS_PATH.exists()/.parent` fail khi `REMINDERS_PATH = str(...)`
  - Fix: `rem_path = Path(REMINDERS_PATH)` wrapper trong `_save_reminders()` và `restore_reminders()` ✅
  - Atomic write: `tempfile.mkstemp(dir=str(rem_path.parent))` + `replace()` ✅

#### 3. Mock Popen không tương thích với DEVNULL
- `subprocess.Popen(cmd, stdout=DEVNULL)` fail với `lambda cmd: ...` trong tests (không nhận kwargs)
  - Fix: thêm `_popen(cmd)` wrapper thử DEVNULL, fallback không kwargs ✅
  - Thay tất cả Popen bằng _popen ✅
- Message UWP thiếu "Store App" → test fail
  - Fix: `"ứng dụng kiểu Store App (UWP)"` ✅

### Nâng cấp v7.0 (đã có sẵn trước fix)

- **tts.py**: RLock, timeout, voice_cache index, fallback engines, health check
- **stt.py**: STT class, RMS fallback struct, thread-safe
- **main.py**: --debug/--no-banner/--config/--engine/--history, signal handling, .history.json, 7.0 banner
- **platform_utils.py**: safe_print, setup_console, is_wsl, capability_report (mới)
- **logging_setup.py**: logging có cấu hình (mới)
- **config.py**: loader config với validation (mới)
- **pyproject.toml**: metadata chuẩn PEP 621 (mới)
- **requirements.txt**: deps với markers python_version (mới)
- **giong_noi_ai.py**: tự tạo thư mục cha cho out_path, check rỗng (fix nhỏ v7.0)
- **giong_nc.py**: tương tự

### Kết quả
- Trước fix: 119 pass / 3 fail + 2 load error
- Sau fix regex + Path: 212 pass / 8 fail
- Sau fix _popen + message: **220 pass / 0 fail** ✅

## Chưa gắn số phiên bản (2026-08-08)

### cai_dat_win10.bat - tự động nhận diện Windows
- Script cài đặt Windows không còn "đoán mò" là Windows 10/11 nữa: giờ tự đọc
  `CurrentBuildNumber` từ registry để phân biệt Windows 7 / 8 / 8.1 / 10 / 11
  (và nhận diện kiến trúc CPU 32-bit / 64-bit / ARM64), rồi chọn đúng nhánh
  cài đặt tương ứng.
- **Nhánh Windows 7**: tự dò tìm Python 3.8.x (bắt buộc trên Win7) qua `py`
  launcher rồi tới `python` trong PATH; báo lỗi kèm link tải rõ ràng nếu
  không thấy đúng bản; kiểm tra sẵn Visual C++ Redistributable 2015-2022
  (x64) trong registry; **không** đổi code page console sang UTF-8 (đồng bộ
  với quyết định trong `platform_utils.setup_console()` - tránh lỗi treo
  console đã ghi nhận trên một số máy Windows 7).
- **Nhánh Windows 8/8.1/10/11**: tự dò Python mới nhất đang có (ưu tiên
  3.13 -> 3.9 qua `py` launcher), cho phép UTF-8 console.
- Cả hai nhánh dùng chung `requirements.txt` - file này đã tự chọn đúng
  phiên bản `scikit-learn`/`joblib` theo `python_version` bằng environment
  marker, nên script chỉ cần gọi đúng 1 lệnh `pip install` duy nhất.
- Tên file giữ nguyên `cai_dat_win10.bat` để không phá vỡ các hướng dẫn cũ
  (vd `FIX_LOI_CYTHON_WIN10.txt`), dù nay đã hỗ trợ mọi bản Windows của dự án.

### cai_dat_giong_ai.bat + giong_noi_ai.py - đồng bộ với engine VieNeu (v6.4)
- **Lỗi nghiêm trọng đã sửa**: `cai_dat_giong_ai.bat` vẫn còn nguyên logic v6.3
  (chỉ cài Piper), trong khi `giong_noi_ai.py` từ v6.4 đã đổi engine mặc định
  sang VieNeu-TTS. Kết quả trước khi sửa: cài xong, bước "tải giọng"/"đọc thử"
  ở cuối script đều âm thầm thất bại vì gói `vieneu` chưa từng được cài.
- Viết lại `cai_dat_giong_ai.bat` (7 bước): kiểm tra phiên bản Python (VieNeu
  cần 3.10+), cài `vieneu` làm engine chính, hỏi tuỳ chọn (`choice`) cài thêm
  `torch`+`torchaudio` cho nhân bản giọng, vẫn giữ cài Piper làm dự phòng như
  cũ (không cần Python 3.10+, nhẹ hơn, dùng khi máy yếu hoặc Python quá cũ).
- **Phát hiện qua đọc source gói `vieneu` (PyPI, bản 3.2.4)**: 10 giọng dựng
  sẵn chạy thuần ONNX/CPU thật (torch-free), nhưng NHÂN BẢN GIỌNG
  (`ref_audio=...`) luôn cần `torchaudio` được cài thêm - `speaker/audio_utils.py`
  import torch/torchaudio ở cấp module cho bước trích đặc trưng giọng nói, dù
  vẫn chạy trên CPU (không cần GPU/CUDA thật). Docstring và `huong_dan_train()`
  trong `giong_noi_ai.py` từng nói "chạy ngay, không cần gì thêm" - đã sửa lại
  cho chính xác.
- `giong_noi_ai.py`: thêm `is_clone_available()` (kiểm tra riêng điều kiện cho
  nhân bản giọng, tách khỏi `is_available()` vốn chỉ xác nhận gói `vieneu`);
  `synth_to_file()` giờ báo lỗi rõ ràng + hướng dẫn cài đặt ngay khi thiếu
  torch/torchaudio thay vì để lỗi ImportError khó hiểu; `kiem_tra()` báo thêm
  trạng thái sẵn sàng nhân bản giọng.
- `requirements-giong-noi.txt`: gắn `python_version >= "3.10"` cho dòng
  `vieneu` (trước đó thiếu - sẽ khiến `pip install -r ...` báo lỗi cứng trên
  Python cũ hơn); thêm 2 dòng chú thích cho `torch`/`torchaudio` (tuỳ chọn).

## v6.3 (2026-08-07)

### Nâng cấp hỗ trợ hệ điều hành (trọng tâm bản này)
- **WSL (Windows Subsystem for Linux) được hỗ trợ thật sự**: trước đây WSL bị
  nhận nhầm là "Linux" thuần nên tắt máy / khởi động lại / khoá màn hình / âm
  lượng / chụp màn hình / mở web / mở file đều âm thầm thất bại (WSL không có
  systemctl/pactl/xdg-open thật). Nay platform_utils.is_wsl() tự phát hiện WSL
  và chuyển tiếp sang Windows host qua cơ chế interop:
  - Lệnh hệ thống -> shutdown.exe / rundll32.exe của Windows
  - Âm lượng -> phím ảo qua powershell.exe
  - Chụp màn hình -> PowerShell + System.Drawing (lưu vào Pictures của Windows)
  - Mở web / mở file -> wslview (sudo apt install wslu) hoặc explorer.exe
  - Đọc giọng nói -> SAPI của Windows host (tts.py)
  - Nếu interop bị tắt, báo lỗi rõ kèm gợi ý kiểm tra /etc/wsl.conf.
- **Phân biệt Windows 10 / Windows 11** (trước đây gộp chung "Windows 10/11";
  Windows 11 = kernel 10.0 build >= 22000).
- **Linux hiện đại hơn**: âm lượng thử wpctl (PipeWire) trước pactl/amixer;
  khoá màn hình thêm qdbus (KDE Plasma); chụp màn hình thêm spectacle (KDE),
  grim (Wayland/Sway) và import (ImageMagick); nhận diện môi trường desktop
  qua linux_desktop() (hiển thị trong báo cáo --sysinfo).
- **Báo cáo khả năng của máy (mới)**: `python main.py --sysinfo` hoặc gõ
  `he thong` trong phiên -> in ra tính năng nào sẽ chạy được trên máy hiện
  tại và thiếu công cụ gì (xem platform_utils.capability_report()).

### Kiểm thử
- Thêm 20 test mới (tổng 220, từ 200 ở v6.2): phát hiện/chuyển tiếp WSL, nhãn
  Windows 11, desktop Linux, chuỗi dự phòng wpctl/qdbus/screenshot, mở URL
  trên WSL, TTS SAPI qua WSL, cờ --sysinfo.
- Các test Linux cũ ép is_wsl() = False để chạy đúng cả khi ai đó chạy bộ
  test trên WSL; test pactl cập nhật theo thứ tự dự phòng mới (wpctl trước).

## v6.2 (2026-08-07)

### Sửa lỗi nghiêm trọng (phát hiện nhờ rà soát vòng 4)
- **intent_model.py - parse_time_expression()**: chữ "tôi" (đại từ) từng bị
  nhận nhầm thành buổi "tối" vì buổi được tìm trên TOÀN câu -> "nhắc tôi họp
  lúc 9 giờ" bị hẹn thành 21h thay vì 9h. Giờ buổi chỉ nhận diện trong phần
  SAU biểu thức giờ (hoặc cụm "tối nay/mai" đứng trước giờ), kèm đối chiếu
  văn bản có dấu để tách "tôi"/"tối".
- **"12 giờ đêm" = 0h** (trước đây 12h trưa), **"1 giờ đêm" = 1h** (trước đây
  13h); hiểu thêm buổi "khuya".
- **Tên riêng "Sáu" không còn bị nhầm thành từ nối "sau"**: dấu hiệu đếm
  ngược giờ kiểm tra trên văn bản CÓ DẤU khi có thể -> "nhắc tôi gọi cho Sáu
  lúc 7 giờ" hẹn đúng 7h (trước đây thành "7 tiếng nữa").
- **nlu_advanced.py - phục hồi dấu**: không còn đổi nhầm một dạng không dấu
  vốn LÀ từ thật trong dataset (vd "hai mươi" từng thành "hải mươi" theo "hải
  phòng").

### Tính năng mới
- **Số viết bằng chữ** trong tính toán và nhắc nhở (hàm mới
  replace_number_words() trong intent_model.py): "mười lăm cộng hai mươi bảy"
  = 42, "hai phẩy năm nhân bốn" = 10, "nhắc tôi họp lúc bảy giờ sáng" = 7:00.
  Hỗ trợ mươi/trăm/nghìn/triệu/tỷ, "lẻ/linh", "phẩy" (thập phân), cả khi gõ
  không dấu. An toàn: "tâm sự" không bị đổi thành "8 sự", "căn bậc hai"
  không thành "căn bậc 2", "phần trăm" không thành "phần 100".
- **Tách nhiều lệnh khi gõ không dấu** ("mo chrome roi phat nhac" -> 2 lệnh);
  "và/va" + động từ không dấu cũng tách được ("mo chrome va tat may").
- **Toán tử nhiều từ**: "chia cho", "nhân với", "cộng với", "trừ đi"; thêm
  căn bậc ba ("căn bậc ba của 27" = 3) và lập phương ("5 lập phương" = 125).
- **Nhắc nhở hiểu thêm**: "nửa tiếng nữa" (30 phút), "1 tiếng rưỡi nữa" (90
  phút), "đặt hẹn giờ 5 phút" (đếm ngược không cần chữ "nữa/sau"), giờ viết
  bằng chữ; bóc nội dung sạch cả đuôi "kém 15" (trước đây còn sót).
- **Lệnh "day" kiểm định tên intent** trước khi ghi feedback.csv (chặn gõ
  nhầm tạo lớp 1-mẫu làm nhiễu lần huấn luyện sau).
- Nhận diện thêm tên miền .ai/.app/.xyz/.me/.tv/.info/.gov/.edu/.shop/...
  ("mở claude.ai") và đường dẫn Windows dùng dấu / ("C:/Users/...").

### Sửa lẻ & hạ tầng
- ID nhắc nhở dùng hậu tố ngẫu nhiên (trước đây 2 lời nhắc đặt trong cùng 1
  giây có thể trùng ID -> gỡ/huỷ nhầm).
- Sửa URL Notion mặc định bị hỏng trong config.py/config.json.
- Sửa toàn bộ ký tự tiếng Việt bị hỏng mã hoá còn sót lại trong tài liệu và
  comment (HUONG_DAN_SU_DUNG.txt, executor.py, intent_model.py,
  train_phobert.py).
- Test không còn ghi vào reminders.json thật của dự án.

### Kiểm thử
- Thêm 29 test mới (tổng 200, từ 170 ở v6.1): lỗi giờ, số bằng chữ, toán tử
  mở rộng, tách lệnh không dấu, kiểm định intent, URL/đường dẫn mới...
- Cập nhật 2 test mã hoá nhầm giới hạn cũ: "3h30" giờ đúng là (3, 30) thay vì
  (15, 30) (v6.1 kỳ vọng theo đúng lỗi "tôi"/"tối"); test "không tính được"
  đổi từ "một cộng một" (nay đã tính được = 2) sang "căn bậc hai của -5".
- Dataset: 779 câu có dấu (từ ~760), 1.558 câu kèm biến thể không dấu.

## v6.1 (2026-08-07)

### Sửa lỗi (phát hiện nhờ rà soát vòng 3)
- **tts.py**: engine giọng nói đã chọn (vd pyttsx3) mà hỏng giữa phiên thì tự động
  thử các engine còn lại (SAPI / macOS say / gTTS) thay vì im lặng bỏ cuộc như v6.0;
  nếu tất cả đều hỏng thì xoá lựa chọn đã cache để lần sau dò lại từ đầu.
- **phobert_model.py**: `MODEL_DIR` chuyển thành đường dẫn TUYỆT ĐỐI neo theo thư mục
  mã nguồn - trước đây là đường dẫn tương đối nên chạy từ thư mục khác (Task
  Scheduler, shortcut, gọi `--once` từ script khác) sẽ không nhận ra model PhoBERT
  đã huấn luyện.

### Kiểm thử
- Thêm 5 test mới (tổng 170): dự phòng engine TTS khi hỏng, không thử lại khi engine
  khoẻ, xoá cache khi mọi engine đều hỏng, `MODEL_DIR` tuyệt đối, `is_trained()` với
  thư mục không tồn tại.

## v6.0 (2026-08-07)

### Sửa lỗi nghiêm trọng
- **Không còn sập khi thiếu scikit-learn/joblib**: toàn bộ import sklearn được bọc
  `try/except`; khi thiếu thư viện, chương trình tự chuyển sang `lite_model.py`
  (trước đây crash ngay lúc khởi động — lỗi nặng nhất trên máy Windows 7/không mạng).
- **URL không còn bị băm nát**: `predict_intent()` nhận thêm `raw_text` (câu gốc) để
  trích xuất thực thể, và `extract_entity()` giờ **luôn** trả URL nguyên vẹn (giữ
  `? = & #`, hoa/thường) bất kể model nhận intent nào. Trước đây
  "mở youtube.com/watch?v=abc123" bị biến thành "youtube.com/watch v abc123".
- **Chặn "bom luỹ thừa"**: `_safe_eval` giới hạn số mũ (|số mũ| ≤ 64, |cơ số| ≤ 10⁶);
  trước đây "9 mũ 9 mũ 9" treo cứng chương trình.
- **"mở file" từ chối file thực thi** (`.exe .bat .ps1 .sh .py .app`… 26 đuôi) và
  chặn đường dẫn chứa `..`. Trước đây "mở file setup.exe" tương đương chạy mã tuỳ ý.
- **Nhắc nhở không còn mất khi thoát app**: tự lưu/khôi phục qua `reminders.json`;
  nhắc nhở đã kêu tự gỡ khỏi danh sách (trước đây nằm mãi trong RAM).
- **"11 giờ đêm" = 23:00** (trước đây hiểu nhầm 11:00 sáng); nhớ được chữ "mai"
  ("7 giờ sáng mai" hẹn sang ngày hôm sau, không kêu ngay hôm nay).
- **Tách địa điểm thời tiết viết lại**: câu không dấu hoạt động đúng
  ("thoi tiet da nang hom nay" → "da nang"); không còn xoá nhầm chữ "Nẵng" trong
  "Đà Nẵng" (do "nắng" và "Nẵng" bỏ dấu là một).
- **2 ngưỡng độ tự tin `confidence_accept` / `confidence_ask` chuyển vào config.json**
  — trước đây viết cứng trong mã nguồn, sửa config không có tác dụng.

### Tính năng mới
- **`lite_model.py`**: Naive Bayes n-gram ký tự (3–4) thuần Python, huấn luyện
  < 1 giây, ~97,7% độ chính xác hold-out, tự kiểm tra fingerprint dataset và tự
  huấn luyện lại khi dữ liệu đổi. `python main.py --version` cho biết đang dùng
  PhoBERT / TF-IDF / LiteModel.
- **Chế độ dòng lệnh**: `--once "câu lệnh"` (chạy 1 lệnh rồi thoát), `--json`
  (xuất JSON cho script), `--version`; chương trình giờ trả mã thoát chuẩn cho shell
  (0 = OK, 1 = lệnh lỗi, 2 = không hiểu).
- **Lệnh phiên mới**: `huy nhac [từ khoá]` (huỷ nhắc nhở), `nap lai` (nạp lại
  config.json không cần khởi động lại).
- **Hiểu giờ giấc phong phú**: `3h30`, `3 giờ rưỡi`, `8 giờ kém 15`, `30 giây nữa`,
  `sáng/trưa/chiều/tối mai`, và toàn bộ dạng trên khi gõ không dấu.
- **Toán tử luỹ thừa bằng lời**: "2 mũ 10" → 1024.
- **`reload_config()` / `set_speech_enabled()`** trong `executor.py` thay cho việc
  gán biến toàn cục trực tiếp từ module khác.

### Hạ tầng & kiểm thử
- **`run_tests.py`**: chạy toàn bộ test **không cần cài pytest** (shim đủ dùng cho
  `fixture`, `parametrize`, `monkeypatch`, `capsys`, `tmp_path`, `raises`, `skipif`);
  nếu máy có pytest thật sẽ tự chuyển sang pytest.
- **165 test** (từ 73 ở bản v5), trong đó ~40 test mới cho các tính năng/sửa lỗi v6.
- `requirements.txt`: scikit-learn/joblib chuyển thành **tuỳ chọn (khuyến nghị)**.
- Thêm `README.md`, `.gitignore`, `conftest.py`, `pytest.ini`.

### Thay đổi hành vi cần lưu ý
- `parse_time_expression()` luôn trả dict đủ khoá
  `{type, minutes, hour, minute, day_offset}` (trước đây chỉ trả khoá tuỳ loại).
- `NLU._judge()` chỉ yêu cầu xác nhận khi intent là `system_control` (tránh hỏi
  xác nhận nhầm các intent khác có chứa từ như "shutdown").
