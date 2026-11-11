# coding=utf-8
"""
NewsNow 平台目录

热榜数据来源于 NewsNow 开源项目（https://github.com/ourongxing/newsnow）。
本目录列出其公开实例支持的平台 ID 与显示名，供 Web 端「监控平台」多选使用。

数据来源：NewsNow shared/sources.json（拉取时间 2026-11-11，共 66 个）。
公共实例的可用平台可能随时间变化，以实际抓取结果为准。
"""

# (id, 名称) —— 按常用程度排序，前 11 个为默认启用
PLATFORM_CATALOG = [
    ("weibo", "微博"),
    ("zhihu", "知乎"),
    ("douyin", "抖音"),
    ("baidu", "百度热搜"),
    ("toutiao", "今日头条"),
    ("bilibili-hot-search", "哔哩哔哩"),
    ("thepaper", "澎湃新闻"),
    ("cls-hot", "财联社"),
    ("wallstreetcn-hot", "华尔街见闻"),
    ("ifeng", "凤凰网"),
    ("tieba", "百度贴吧"),
    ("kuaishou", "快手"),
    ("hupu", "虎扑"),
    ("douban", "豆瓣"),
    ("xueqiu", "雪球"),
    ("xueqiu-hotstock", "雪球热股"),
    ("gelonghui", "格隆汇"),
    ("fastbull", "法布财经"),
    ("fastbull-express", "法布财经快讯"),
    ("fastbull-news", "法布财经新闻"),
    ("mktnews", "MKTNews"),
    ("mktnews-flash", "MKTNews快讯"),
    ("jin10", "金十数据"),
    ("36kr", "36氪"),
    ("36kr-quick", "36氪快讯"),
    ("36kr-renqi", "36氪人气"),
    ("ithome", "IT之家"),
    ("sspai", "少数派"),
    ("juejin", "稀土掘金"),
    ("nowcoder", "牛客"),
    ("v2ex", "V2EX"),
    ("v2ex-share", "V2EX分享"),
    ("hackernews", "Hacker News"),
    ("producthunt", "Product Hunt"),
    ("github", "Github"),
    ("github-trending-today", "Github今日热榜"),
    ("solidot", "Solidot"),
    ("linuxdo", "LinuxDo"),
    ("freebuf", "Freebuf"),
    ("chongbuluo", "虫部落"),
    ("chongbuluo-latest", "虫部落最新"),
    ("chongbuluo-hot", "虫部落最热"),
    ("coolapk", "酷安"),
    ("smzdm", "什么值得买"),
    ("pcbeta", "远景论坛"),
    ("pcbeta-windows11", "远景论坛Win11"),
    ("steam", "Steam"),
    ("tencent", "腾讯新闻"),
    ("tencent-hot", "腾讯新闻热点"),
    ("qqvideo", "腾讯视频"),
    ("qqvideo-tv-hotsearch", "腾讯视频热搜"),
    ("iqiyi", "爱奇艺"),
    ("iqiyi-hot-ranklist", "爱奇艺热榜"),
    ("dongqiudi", "懂球帝"),
    ("zaobao", "联合早报"),
    ("cankaoxiaoxi", "参考消息"),
    ("kaopu", "靠谱新闻"),
    ("sputniknewscn", "卫星通讯社"),
    ("aihot", "AIHOT"),
    ("bilibili", "哔哩哔哩综合"),
    ("bilibili-hot-video", "哔哩哔哩热视频"),
    ("bilibili-ranking", "哔哩哔哩排行榜"),
    ("cls", "财联社综合"),
    ("cls-telegraph", "财联社电报"),
    ("cls-depth", "财联社深度"),
    ("wallstreetcn", "华尔街见闻综合"),
    ("wallstreetcn-quick", "华尔街见闻快讯"),
    ("wallstreetcn-news", "华尔街见闻新闻"),
]

# 默认启用的平台（与本地版 config/config.yaml 保持一致）
DEFAULT_PLATFORM_IDS = [
    "toutiao", "baidu", "wallstreetcn-hot", "thepaper", "bilibili-hot-search",
    "cls-hot", "ifeng", "tieba", "weibo", "douyin", "zhihu",
]

# 平台域名安全校验规则（id -> 预期主域名），来自本地版 config.yaml
PLATFORM_DOMAINS = {
    "toutiao": "toutiao.com",
    "baidu": "baidu.com",
    "wallstreetcn-hot": "wallstreetcn.com",
    "thepaper": "thepaper.cn",
    "bilibili-hot-search": "bilibili.com",
    "cls-hot": "cls.cn",
    "ifeng": "ifeng.com",
    "tieba": "baidu.com",
    "weibo": "weibo.com",
    "douyin": "douyin.com",
    "zhihu": "zhihu.com",
    "kuaishou": "kuaishou.com",
    "hupu": "hupu.com",
    "douban": "douban.com",
    "xueqiu": "xueqiu.com",
    "gelonghui": "gelonghui.com",
    "fastbull": "fastbull.com",
    "mktnews": "mktnews.com",
    "jin10": "jin10.com",
    "36kr": "36kr.com",
    "ithome": "ithome.com",
    "sspai": "sspai.com",
    "juejin": "juejin.cn",
    "nowcoder": "nowcoder.com",
    "v2ex": "v2ex.com",
    "hackernews": "news.ycombinator.com",
    "producthunt": "producthunt.com",
    "github": "github.com",
    "solidot": "solidot.org",
    "linuxdo": "linux.do",
    "freebuf": "freebuf.com",
    "chongbuluo": "chongbuluo.com",
    "coolapk": "coolapk.com",
    "smzdm": "smzdm.com",
    "pcbeta": "pcbeta.com",
    "steam": "steampowered.com",
    "tencent": "qq.com",
    "qqvideo": "v.qq.com",
    "iqiyi": "iqiyi.com",
    "dongqiudi": "dongqiudi.com",
    "zaobao": "zaobao.com",
    "cankaoxiaoxi": "cankaoxiaoxi.com",
    "kaopu": "kaopu.com",
    "sputniknewscn": "sputniknews.cn",
    "aihot": "aihot.com",
    "bilibili": "bilibili.com",
    "cls": "cls.cn",
    "wallstreetcn": "wallstreetcn.com",
}

PLATFORM_NAMES = {pid: name for pid, name in PLATFORM_CATALOG}


def get_platform_name(platform_id: str) -> str:
    """获取平台显示名，未知 ID 原样返回"""
    return PLATFORM_NAMES.get(platform_id, platform_id)


def get_platform_domain(platform_id: str) -> str:
    """获取平台域名安全校验规则，未配置返回空串（不校验）"""
    return PLATFORM_DOMAINS.get(platform_id, "")
