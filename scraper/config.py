"""Boss 直聘抓取工具的集中配置。

页面改版时，优先只修改本文件：所有 CSS selector、正则表达式、黑名单和
等待/滚动参数都集中在这里。selector 按顺序尝试，越靠前优先级越高。
"""

# 0 表示不限数量、抓取全部会话；如需小规模试跑可临时改成 10。
MAX_ITEMS = 0

# CDP_ENDPOINT：浏览器远程调试地址，通常无需修改。
# 必须写 127.0.0.1 而不是 localhost：localhost 会先解析成 IPv6 ::1，而
# Brave/Chrome 的调试端口只监听 IPv4，导致 ECONNREFUSED ::1:9222（实测）。
CDP_ENDPOINT = "http://127.0.0.1:9222"
# TARGET_DOMAIN：用于从已打开标签页中识别 Boss 直聘页面。
TARGET_DOMAIN = "zhipin.com"
# CHAT_URL_FRAGMENT：用于确认当前位于“沟通”模块。
# 注意（2026-08-31 实测）：/web/chat/index 和 /web/chat/recommend 都是沟通模块的
# 子路由（recommend 是内嵌的推荐 tab），聊天列表在两者下都存在，不能只认 index。
CHAT_URL_FRAGMENT = "/web/chat"
# CHAT_URL：沟通页完整地址；不在沟通页时脚本会先尝试自动跳转到这里。
CHAT_URL = "https://www.zhipin.com/web/chat/index"
# GOTO_TIMEOUT_MS：自动跳转沟通页时等待页面加载的最长毫秒数。
GOTO_TIMEOUT_MS = 30000
# OUTPUT_DIR_NAME：结果目录名，相对于交付包根目录。
OUTPUT_DIR_NAME = "输出"

# WAIT_MIN / WAIT_MAX：每个会话完成后的随机短等待秒数。
WAIT_MIN = 2.0
WAIT_MAX = 4.0
# LONG_BREAK_EVERY：每处理多少个会话长休一次；设为 0 可关闭长休。
LONG_BREAK_EVERY = 30
# LONG_BREAK_MIN / LONG_BREAK_MAX：长休的随机秒数范围。
LONG_BREAK_MIN = 120.0
LONG_BREAK_MAX = 300.0
# SECURITY_RECHECK_SECONDS：登录失效或验证码出现时的重查间隔。
SECURITY_RECHECK_SECONDS = 15.0

# RENDER_TIMEOUT_SECONDS：点击会话后等待候选人面板刷新的最长秒数。
RENDER_TIMEOUT_SECONDS = 10.0
# SELECTOR_TIMEOUT_MS：读取单个页面元素文本的最长毫秒数。
SELECTOR_TIMEOUT_MS = 1500
# CLICK_TIMEOUT_MS：滚动到会话项及点击操作的最长毫秒数。
CLICK_TIMEOUT_MS = 5000
# CDP_TIMEOUT_MS：连接调试浏览器的最长毫秒数。
CDP_TIMEOUT_MS = 10000
# ITEM_RETRY_COUNT：首次失败后对单个会话额外重试的次数。
ITEM_RETRY_COUNT = 2
# MIN_TIMED_ITEMS：容器内至少多少个子项带消息时间，才认定为真实会话列表。
MIN_TIMED_ITEMS = 3
# NAVIGATION_RECOVERY_TIMEOUT_SECONDS：误跳页后等待返回沟通页的最长秒数。
NAVIGATION_RECOVERY_TIMEOUT_SECONDS = 10.0

# PAGE_READY_TIMEOUT_SECONDS：启动后等待沟通页渲染出会话列表的最长秒数。
# SPA 首次加载可能要十几秒，期间所有元素都不存在，不能立刻判失败。
PAGE_READY_TIMEOUT_SECONDS = 90.0
# PAGE_READY_POLL_SECONDS：等待页面就绪的轮询间隔秒数。
PAGE_READY_POLL_SECONDS = 2.0
# PAGE_ACQUIRE_RETRY / PAGE_ACQUIRE_WAIT：锁定稳定页面的重试次数与确认间隔。
# 用于排除 Chromium 预渲染的幽灵标签页（连上后瞬间被销毁）。
PAGE_ACQUIRE_RETRY = 8
PAGE_ACQUIRE_WAIT = 1.5

# NO_LIST_RETRY / NO_LIST_RETRY_WAIT：抓取中途会话列表暂时消失时的重试次数与间隔秒数。
NO_LIST_RETRY = 5
NO_LIST_RETRY_WAIT = 3.0
# RECOMMEND_FRAGMENT：Boss 会自行把沟通页跳到这个推荐子页，且在部分账号上
# 永远卡在"加载中"白屏（2026-09-01 实测）。列表消失且 URL 命中它时，
# 脚本会主动 goto 回 CHAT_URL 拉回沟通页。
RECOMMEND_FRAGMENT = "/web/chat/recommend"
# NAV_CHAT_TEXTS：左侧「沟通」菜单的文字，用于 JS 强制点击切回聊天视图。
NAV_CHAT_TEXTS = ("沟通", "消息")
# HELP_POLL_SECONDS：请用户手动点「沟通」后，多久检查一次列表是否出现。
HELP_POLL_SECONDS = 3.0

# POPUP_DISMISS_TEXTS：弹窗关闭按钮文字白名单。
# 严禁加入"立即体验""开始使用""跳过""去看看"等推广按钮文字——Boss 的横幅
# 用的就是这些字，点下去会跳到推荐页且再也回不来（2026-09-01 实测事故）。
# 只允许纯关闭语义的词。
POPUP_DISMISS_TEXTS = ("我知道了", "知道了")
# POPUP_CONTAINER_HINTS：只有位于这些容器（类名/role 含以下片段）内部的
# 按钮才允许点击，避免误点页面主体上的业务元素。
POPUP_CONTAINER_HINTS = ("dialog", "popup", "modal", "guide", "mask", "tip", "layer")

# DEBUG_MAX_FAILURE_DUMPS：单次运行最多为失败会话生成几份诊断包（防止刷屏占盘）。
DEBUG_MAX_FAILURE_DUMPS = 3
# DEBUG_TEXT_PREVIEW_CHARS：诊断报告中每个元素文本预览的最大字符数。
DEBUG_TEXT_PREVIEW_CHARS = 120
# DEBUG_MAX_ITEMS_IN_REPORT：诊断报告中最多列出的会话项解析结果条数。
DEBUG_MAX_ITEMS_IN_REPORT = 5

# SCROLL_RETRY：连续多少次滚动未出现新 key 后判定到达列表底部。
SCROLL_RETRY = 5
# SCROLL_WAIT_SECONDS：每次滚动后等待虚拟列表加载的秒数。
SCROLL_WAIT_SECONDS = 1.5
# SCROLL_STEP_RATIO：每次滚动距离占列表可视高度的比例。
SCROLL_STEP_RATIO = 0.85
# SCROLL_MIN_PIXELS：列表很矮时仍保证的最小滚动像素数。
SCROLL_MIN_PIXELS = 500

# SELF_INTRO_MAX_CHARS：写入 CSV 的自我介绍最大字符数。
SELF_INTRO_MAX_CHARS = 500
# MARKDOWN_INTRO_MAX_CHARS：data.md 中自我介绍摘要最大字符数。
MARKDOWN_INTRO_MAX_CHARS = 50
# FILENAME_MAX_CHARS：截图和原文文件中的姓名部分最大字符数。
FILENAME_MAX_CHARS = 60

# SYSTEM_ACCOUNTS：命中即直接跳过、不写入 CSV 的系统会话名。
SYSTEM_ACCOUNTS = {
    "Boss直聘小助手",
    "BOSS直聘小助手",
    "系统通知",
    "BOSS直聘",
    "Boss直聘",
    "牛人管家",
    "直聘小助手",
    "平台通知",
}

# NAV_BLOCKLIST：左侧全局导航名称；精确命中时绝不点击，并记为 skipped_nav。
NAV_BLOCKLIST = {
    "职位管理",
    "推荐牛人",
    "搜索",
    "沟通",
    "意向沟通",
    "互动",
    "牛人管理",
    "道具",
    "工具箱",
    "更多",
    "招聘规范",
    "我的客服",
    "面试",
    "招聘数据",
    "账号权益",
    "升级VIP",
    "新招呼",
}

# SECURITY_KEYWORDS：候选人面板消失时，用于识别验证码/安全检查/未登录的正文词。
# 注意：不要放过于宽泛的词（如裸的“验证”），聊天内容里出现会导致误判卡住。
SECURITY_KEYWORDS = (
    "安全检查",
    "请完成验证",
    "滑块验证",
    "异常访问",
    "访问过于频繁",
    "扫码登录",
    "微信扫码",
    "账号密码登录",
    "APP扫码",
)
# LOGIN_URL_KEYWORDS：用于判断登录态失效的 URL 片段。
LOGIN_URL_KEYWORDS = ("/login", "passport.zhipin.com")
# ATTACHMENT_KEYWORDS：用于判断当前会话是否存在附件简历的文本词。
ATTACHMENT_KEYWORDS = ("附件简历", ".pdf", "在线简历")

# ACTIVE_CLASS_TOKENS：会话项 class 中表示“当前已选中”的标记。
ACTIVE_CLASS_TOKENS = ("active", "selected", "current")
# ACTIVE_STATE_ATTRIBUTES：会话项上可直接表示选中状态的 DOM 属性。
ACTIVE_STATE_ATTRIBUTES = ("aria-selected", "data-active", "data-selected")
# ACTIVE_STATE_VALUES：上述状态属性代表“已选中”的值。
ACTIVE_STATE_VALUES = ("true", "1", "yes")

# 优先读取这些 DOM 属性作为会话稳定 key。
# 实测（2026-08-31，来自真实 DOM dump）：会话项是 div[role='listitem']，
# 自带 key="51934788-0" 这类唯一 ID。
KEY_ATTRIBUTES = (
    "key",
    "data-geek-id",
    "data-geekid",
    "data-id",
    "data-uid",
    "data-user-id",
    "geek-id",
)

# 所有页面 CSS selector。每组依次尝试，便于 Boss 页面改版后单点调整。
SELECTORS = {
    "body": ("body",),
    # 实测类名（2026-08-31 真实 DOM）：容器 .user-list，项 [role='listitem']，
    # 姓名 .geek-name，沟通职位 .source-job，摘要 .push-text，时间 .time。
    "conversation_list": (
        ".user-list",
        "[class*='user-list']",
        ".chat-list",
        "[class*='chat-list']",
        "[class*='conversation-list']",
        "[class*='chatList']",
    ),
    "conversation_item": (
        ":scope [role='listitem']",
        ":scope [class*='geek-item-wrap']",
        ":scope > [data-geek-id]",
        ":scope > [data-id]",
        ":scope li[class*='item']",
        ":scope [class*='chat-item']",
        ":scope [class*='conversation-item']",
        ":scope [class*='friend-item']",
    ),
    "item_name": (
        ".geek-name",
        "[class*='geek-name']",
        "[class*='name']",
        "[class*='title']",
        "h3",
    ),
    "item_job": (
        ".source-job",
        "[class*='source-job']",
        "[class*='job']",
        "[class*='position']",
    ),
    "item_summary": (
        ".push-text",
        "[class*='push-text']",
        "[class*='last-msg']",
        "[class*='message']",
        "[class*='summary']",
        "[class*='content']",
    ),
    "item_time": (
        "[class*='time']",
        "time",
    ),
    "right_panel": (
        ".chat-conversation",
        "[class*='chat-conversation']",
        "[class*='conversation-main']",
        "[class*='chat-content']",
        "[class*='chatContent']",
    ),
    "candidate_panel": (
        "[class*='geek-card']",
        "[class*='candidate-card']",
        "[class*='resume-card']",
        "[class*='geek-info']",
        "[class*='candidate-info']",
        "[class*='base-info']",
    ),
    "candidate_name": (
        "[class*='geek-name']",
        "[class*='candidate-name']",
        "[class*='user-name']",
        "[class*='name']",
        "h3",
        "h2",
    ),
    "age": ("[class*='age']",),
    "work_years": (
        "[class*='experience']",
        "[class*='work-year']",
        "[class*='workYear']",
    ),
    "education": (
        "[class*='degree']",
        "[class*='education'] [class*='level']",
    ),
    "school": (
        "[class*='education'] [class*='school']",
        "[class*='school']",
    ),
    "major": (
        "[class*='education'] [class*='major']",
        "[class*='major']",
    ),
    "recent_company": (
        "[class*='work'] [class*='company']",
        "[class*='company']",
    ),
    "recent_role": (
        "[class*='work'] [class*='position']",
        "[class*='work'] [class*='job']",
        "[class*='company'] + *",
    ),
    "expected_city": (
        "[class*='expect'] [class*='city']",
        "[class*='intention'] [class*='city']",
    ),
    "expected_role": (
        "[class*='expect'] [class*='position']",
        "[class*='intention'] [class*='job']",
    ),
    "expected_salary": (
        "[class*='expect'] [class*='salary']",
        "[class*='salary']",
    ),
    "communication_role": (
        "[class*='communication-job']",
        "[class*='chat-job']",
        "[class*='position-name']",
    ),
    "candidate_message": (
        "[class*='message-item'][class*='friend'] [class*='text']",
        "[class*='message-item'][class*='geek'] [class*='text']",
        "[class*='message-left'] [class*='text']",
        "[class*='item-friend'] [class*='message']",
    ),
    "resume_attachment": (
        "[class*='resume']",
        "[class*='attachment']",
        "[class*='file-card']",
        "a[href*='.pdf']",
    ),
}

# CSV 字段到 selector 组的映射。取不到时 main.py 会使用下方正则兜底。
FIELD_SELECTOR_MAP = {
    "姓名": "candidate_name",
    "年龄": "age",
    "工作年限": "work_years",
    "学历": "education",
    "学校": "school",
    "专业": "major",
    "最近公司": "recent_company",
    "最近职位/技术栈": "recent_role",
    "期望城市": "expected_city",
    "期望职位": "expected_role",
    "期望薪资": "expected_salary",
    "沟通职位": "communication_role",
}

# 所有文本解析正则。均使用命名分组，方便页面改版时只调整本文件。
REGEX_PATTERNS = {
    "age": r"(?P<value>\d{1,2})\s*岁",
    "work_years": r"(?<!\d)(?P<value>\d{1,2})\s*年(?:工作经验|经验)?(?!\s*\d{1,2}\s*月)",
    "education": r"(?P<value>博士|硕士|本科|大专|高中|中专|初中)",
    "salary": r"(?P<value>\d+(?:\.\d+)?\s*-\s*\d+(?:\.\d+)?\s*[Kk](?:\s*[·・]\s*\d+薪)?)",
    "expectation": r"(?:期望|求职期望)\s*[:：]?\s*(?P<city>[^·・|\s\n]{2,12})\s*[·・|]\s*(?P<role>[^\n]*?)\s+(?P<salary>\d+(?:\.\d+)?\s*-\s*\d+(?:\.\d+)?\s*[Kk](?:\s*[·・]\s*\d+薪)?)",
    "communication_role": r"(?:沟通职位|应聘职位|沟通岗位)\s*[:：]?\s*(?P<value>[^\n]+)",
    "education_entry": r"(?:教育经历|教育背景)\s*(?:(?:\d{4}(?:[./-]\d{1,2}|年\d{1,2}月)\s*[-至~—]+\s*(?:\d{4}(?:[./-]\d{1,2}|年\d{1,2}月)|至今))\s*)?(?P<school>[^\n·・|]{2,50}?(?:大学|学院|学校))\s*[·・|]\s*(?P<major>[^\n·・|]{1,50})(?:\s*[·・|]\s*(?P<degree>博士|硕士|本科|大专|高中|中专))?",
    "school": r"(?P<school>[\u4e00-\u9fffA-Za-z0-9()（）·\-]{2,50}(?:大学|学院|学校))",
    "work_entry": r"(?:工作经历|最近工作|工作经验)\s*(?:(?:\d{4}(?:[./-]\d{1,2}|年\d{1,2}月)\s*[-至~—]+\s*(?:\d{4}(?:[./-]\d{1,2}|年\d{1,2}月)|至今))\s*)?(?P<company>[^\n·・|]{2,60}?)\s*[·・|]\s*(?P<role>[^\n]{1,80})",
    "name_line": r"(?m)^(?P<value>[\u4e00-\u9fffA-Za-z·•]{2,30})$",
    "last_message_time": r"(?P<value>(?:今天|昨天)?\s*\d{1,2}:\d{2}|\d{1,2}月\d{1,2}日|\d{4}[./-]\d{1,2}[./-]\d{1,2})",
    "self_intro": r"(?:自我介绍|个人介绍)\s*[:：]\s*(?P<value>[^\n]{1,500})",
    "filename_invalid": r"[<>:\"/\\|?*\x00-\x1f]",
    "whitespace": r"\s+",
}

CSV_COLUMNS = (
    "序号",
    "姓名",
    "年龄",
    "工作年限",
    "学历",
    "学校",
    "专业",
    "最近公司",
    "最近职位/技术栈",
    "期望城市",
    "期望职位",
    "期望薪资",
    "沟通职位",
    "自我介绍",
    "有附件简历",
    "最后消息时间",
    "截图文件名",
)

CANDIDATE_EVIDENCE_FIELDS = (
    "年龄",
    "工作年限",
    "学历",
    "学校",
    "专业",
    "最近公司",
    "最近职位/技术栈",
    "期望城市",
    "期望职位",
    "期望薪资",
    "沟通职位",
)

MARKDOWN_COLUMNS = (
    ("姓名", "姓名"),
    ("学历", "学历"),
    ("学校", "学校"),
    ("年限", "工作年限"),
    ("期望薪资", "期望薪资"),
    ("期望职位", "期望职位"),
    ("城市", "期望城市"),
    ("自我介绍摘要", "自我介绍"),
)
