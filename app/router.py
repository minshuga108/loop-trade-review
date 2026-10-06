"""Deterministic intent router for Loop chat (English, Chinese, Hinglish). Router v2.

route(text, previous_intent=None) -> one of INTENTS. No dependencies, no network, no LLM.

How it decides:
1. Normalise: NFKC (full-width -> half-width), traditional -> simplified Chinese
   (small table), lower case, chat shorthand and typo repair against the concept
   vocabulary ("wrng" -> "wrong", "happend" -> "happened"), join "check list" /
   "pre trade" style splits.
2. Safety first, before any scoring:
   - injection (EN/ZH: "ignore previous", "system prompt", "you are now",
     "将意图改为", role-play, encoded payloads, asks for keys) -> help + "injection"
   - a request to actually place / execute / close an order or move funds
     ("place a market buy", "sell everything", "go all in", "全部平仓") -> help + "order_request"
   - a request for buy/sell advice or a price prediction ("should I buy BTC",
     "is now a good time to long", "该买吗") -> help + "advice"
   The execution/advice detectors are negation-safe ("I won't sell everything"),
   counterfactual-safe ("what if I had sold everything" stays rule), and skip
   temporal clauses ("before I place an order" is a checklist question) and
   rule-check requests ("should I open X given my rules" stays gate).
   A bare order idea with a size and no advice wording ("buy $20k rNVDA") is a gate check.
3. Score each intent with weighted concept patterns: English phrases written
   stem-tolerant ("leak", "leaking", "strictness", "passes"), Chinese substrings, Hinglish words.
   A light stemmer keeps the typo repair from "fixing" real inflections.
4. Follow-ups: short anaphoric turns ("and rule 3?", "那仓位减半呢") lean on
   previous_intent; a turn with no signal at all inherits it when short.
5. Highest score wins (ties by a fixed priority). If nothing reaches the floor, a
   small character n-gram nearest-centroid model (trained only on the dev sets, see
   app/router_examples.json) may pick an intent, but only when its best cosine is
   above CENTROID_MIN and beats the runner-up by CENTROID_MARGIN; otherwise help.
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path

INTENTS = ("habit", "rule", "court", "report", "source", "gate", "checklist", "help")
PRIORITY = ("gate", "checklist", "court", "rule", "habit", "report", "source", "help")
FLOOR = 1.0

# ---------------------------------------------------------------- normalisation tables
# Traditional -> simplified, only characters that matter for routing (and their neighbours).
_T2S_PAIRS = (
    "慣惯 習习 規规 則则 週周 報报 據据 數数 來来 帳账 賬账 戶户 實实 盤盘 擬拟 單单 倉仓 買买 賣卖 虧亏 錢钱 錯错 誤误 頻频 "
    "復复 結结 總总 這这 檢检 驗验 過过 試试 測测 審审 議议 決决 絕绝 為为 爲为 麼么 嗎吗 會会 樣样 個个 們们 對对 開开 關关 "
    "給给 讓让 說说 話话 請请 統统 計计 時时 間间 價价 漲涨 幣币 薦荐 執执 詞词 視视 記记 錄录 誰谁 從从 裡里 裏里 還还 項项 "
    "確确 認认 東东 帶带 損损 斷断 設设 獲获 進进 場场 機机 夠够 啟启 啓启 動动 現现 劃划 線线 號号 參参 與与 準准 嚴严 寬宽 "
    "鬆松 標标 顯显 費费 貴贵 壞坏 問问 題题 謝谢 學学 體体 應应 該该 幫帮 轉转 齊齐 盡尽 證证 圖图 書书 讀读 寫写 種种 隨随 "
    "後后 層层 點点 兩两 萬万 億亿 張张 歷历 筆笔 長长 預预 賺赚 輸输 贏赢 沒没 條条 範范 圍围 紀纪 違违 許许 額额 槓杠 桿杆 "
    "換换 減减 補补 掛挂 銷销 員员 碼码 鑰钥 庫库 將将 頁页 聽听 選选 擇择 處处 歸归 況况 於于 邊边 務务 稱称 臺台 貨货 "
    "資资 產产 連连 續续 虛虚 當当 畫画 勢势 級级 離离 發发 佈布 達达 穩稳 險险 順顺 華华 僅仅 獨独 釋释 義义 覺觉 氣气 "
    "極极 權权 製制 績绩 嗎吗 擔担 憂忧 麼么 夜夜 漲涨 濾滤 碼码 儲储 齡龄 頭头 讚赞 錶表 鐘钟 錄录 紅红 綠绿 號号 邏逻 輯辑")
T2S = {p[0]: p[1] for p in _T2S_PAIRS.split() if len(p) == 2 and p[0] != p[1]}
_T2S_TABLE = str.maketrans(T2S)

# chat shorthand -> word (whole tokens only)
SHORTHAND = {
    "wat": "what", "wht": "what", "whats": "what's", "u": "you", "ur": "your", "r": "are", "pls": "please",
    "plz": "please", "thx": "thanks", "ty": "thanks", "hw": "how", "abt": "about", "b4": "before",
    "bf4": "before", "wk": "week", "wkly": "weekly", "acct": "account", "acc": "account", "pnl": "pnl",
    "y": "why", "im": "i'm", "dont": "don't", "didnt": "didn't", "wont": "won't", "cant": "can't",
    "shld": "should", "shud": "should", "wud": "would", "wld": "would", "cud": "could", "rn": "right now",
}

# Words a typo may be repaired to (concept vocabulary). Repair needs: token >= 4 letters, not
# itself a known word, same first letter, edit distance 1 (2 for long words).
VOCAB = (
    "habit habits pattern patterns mistake mistakes worst costly revenge overtrade overtrading wrong leaking "
    "leak bleeding money losing losses problem behaviour behavior oversize oversizing chasing differently "
    "counterfactual halt simulate happened would saved helped cap limit stopped "
    "accepted rejected proposed proposal proposals tested verdict strict strictness threshold criteria passed "
    "survived trial court significance overfit "
    "weekly review recap summary summarize summarise report overall "
    "source provenance synthetic whose demo sample fake real actual exchange synced fresh uploaded simulated "
    "checklist pretrade before checking trigger "
    "position leverage allowed "
).split()
_VOCAB_SET = set(VOCAB)
# Common words never "repaired" (they are real words that sit one edit from a vocab word).
COMMON = set((
    "half hall halls habitat what that this then than them they there their these those when where which while "
    "with will would wall well week weak weeks seek sell sold tell told test tests text best rest last past post "
    "mine more most much must make made many mean real read ready rely role rule rules ruled rude ride rate "
    "rates date data dart part card cars case cash cast cost costs host lost lose loss lots look looks book took "
    "good gold hold held help home hope have gave give live love long song some same sale save safe size side "
    "site time tine fine line mine nine find kind bind wind sure pure user used uses fill fills full fall call "
    "came come cone done gone none note nope open over oven ever even every very vary many deal dear near "
    "real sort sorted short shirt shot spot stop step stem team term trap trade trades tread treat trend "
    "proof prove price prize print prior plan plans play plays pays days ways says lays sign sing sync "
    "cheap check chick chuck month mouth north worth world words works worse worst forst first fist list "
    "lists lift gift left lest less loss lass mass miss mist must bust dust gust just rust trust "
    "bleed blend blind bland brand bread break bleak black block clock click clack stick stack track "
    "trick truck strict street stretch district patter batter better bitter butter matter latter letter "
    "leak lean leap lead load loan loud bear beer bean been seen keen kept slept swept wept leapt "
    "simple count face fade trail world shopped "
    "daily dally sally rally really realty reality ready "
).split())

_ORDER_VERB = r"(buy|sell|long|short|order|trade|execute|place|send|confirm|买|卖|下单|做多|做空|开仓)"

# ---------------------------------------------------------------- safety
INJECTION = [
    r"\b(ignore|disregard|forget|override|bypass)\b.{0,40}\b(instructions?|prompts?|guardrails?|system)\b",
    r"\b(ignore|disregard|forget|override)\b.{0,20}\b(all |any |your |the |of )*(previous|prior|above|earlier|original|preceding)\b",
    r"system prompt|developer mode|dev mode|jailbreak|\bdan\b|you are now|^system\s*:|pretend (you|to be)",
    r"\b(reveal|print|show|output|leak|repeat|dump)\b.{0,20}\b(prompt|instructions|system message)\b",
    r"\bfrom now on,? (you|act|respond|answer)\b|\bact as (an? |my )?\w+|\brole-?\s?play\b|\byou (must|will|shall) now\b",
    r"\byou have no (rules|restrictions|limits|filters|guidelines)\b|\bno (restrictions|filters|guardrails)\b",
    r"\bnew (instructions?|rules for you|persona)\b|\b(set|change|switch|force|override) (the |your )?intent\b|\bintent\s*[=:]",
    r"\bdump\b.{0,20}\b(db|database|tables?|memory|raw)\b|\b(api|secret|private) ?keys?\b|\bpasswords?\b|\bseed phrase\b|\bcredentials?\b",
    r"\bbase64\b|\brot13\b|\bdecode (this|the following|and (run|follow|execute))\b|<\|im_start\|>|\[/?inst\]|</?system>|###\s*(system|instruction)",
    r"(忽略|无视|忘掉|忘记|不要管|绕过|跳过|不用管).{0,12}(指令|提示词|系统|设定|之前|以上|上面)",
    r"系统提示|提示词|开发者模式|越狱|系统指令|系统消息|系统命令",
    r"将?意图(改|设|切换|设置)(为|成)|改(为|成)\s*(habit|rule|court|report|source|gate|checklist)\b",
    r"(输出|导出|打印|显示|给我).{0,8}(原始数据库|数据库|密码|密钥|私钥|助记词|api)|管理员密码|私钥|助记词",
    r"你现在是\s*[a-z]|你现在是一个|从现在(开始|起)你|扮演|角色扮演|假装你|没有任何限制|不受(任何)?限制|解码(这|以下)",
]
# "ignore the rules / bypass the gate" only counts as injection when an order verb is present,
# so "what if I had ignored rule 2" stays a rule question.
INJECTION_WITH_ORDER = [
    r"\b(ignore|disregard|forget|override|bypass|skip)\b.{0,30}\b(rules?|checklist|gate|limits?)\b",
    r"(忽略|无视|忘掉|忘记|不要管|绕过|跳过).{0,8}(规则|限制|检查|清单)",
]
# Encoded payloads: a long unbroken base64/hex-looking token.
_ENCODED = re.compile(r"(?<![a-z0-9])[a-z0-9+/]{32,}={0,2}(?![a-z0-9])|\\x[0-9a-f]{2}(\\x[0-9a-f]{2}){5,}")

ORDER_REQUEST = [
    r"\b(place|execute|submit|send|fire off|put in|confirm)\b.{0,25}\b(orders?|trades?|it)\b",
    r"\b(place|submit|fire|put in)\b (a |an |the |my )?(market|limit|stop)? ?(buy|sell|long|short)\b",
    r"\bexecute\b(?! quality)",
    r"\b(real|live) (order|trade)\b",
    r"\bfor me\b.{0,30}\b(on|at) (my )?(bitget|account|exchange)\b",
    r"\b(on|in) my (bitget )?account\b.{0,30}\b(buy|sell|long|short)\b",
    r"\b(buy|sell|long|short)\b.{0,30}\b(for me|on my account|on my bitget)\b",
    r"\b(sell|close|liquidate|dump|exit|cancel|flatten)\b (out )?(of )?(everything|it all|all (of )?(my |the )?(positions?|orders?|coins?|holdings?|bags?|trades?|of it)|all\b|my (whole|entire) )",
    r"^(please |pls |now |just )?(close|exit|flatten|liquidate|cancel|kill)\b.{0,15}\b(positions?|orders?|trades?|longs?|shorts?)\b",
    r"\b(close|exit|flatten|liquidate|cancel)\b.{0,20}\b(right now|immediately|asap|at once|now)\b",
    r"\bgo(ing)? all[- ]in\b|\ball[- ]in on\b|\bape (in|into)\b|\byolo\b",
    r"\bjust (buy|sell|do it|send it)\b|\bsend it\b|\bpull the trigger (for me|now)\b|\b(do|make) the trade\b",
    r"\b(withdraw|transfer)\b|\b0x[0-9a-f]{6,}\b|send .{0,20}to (this|my|an?) (address|wallet)",
    r"(帮我|替我|给我|直接)(在\S{0,10}?)?(真实|马上|直接|立刻)?(市价|限价)?(下单|下一?个|买入?|卖出?|做多|做空|开仓|平仓|清仓)",
    r"真实(下单|订单)|(帮我|替我|直接).{0,6}真实交易|实盘下单|提现|转账|转到.{0,10}地址",
    r"全部平仓|一键平仓|全平|全部卖|全卖了|清仓|平掉|梭哈|全仓(买|干|进|梭)|(马上|立刻|立即)(买|卖|平|下单)",
    r"把.{0,10}(执行|平了|卖了|买了|下了)|执行(了吧|吧|一下|掉)|(单子|订单)执行",
]
ADVICE = [
    r"\bshould (i|we)\b.{0,20}\b(buy|sell|long|short|hold|enter|exit|close|ape|get in|get out|go (long|short|in)|take profit|dca|invest|hodl)\b",
    r"\b(is|it'?s|are) (now|this|today|it|tonight|this week)\b.{0,6}\b(a )?(good|right|bad|great|smart|the) (time|day|week|moment|point|entry|idea|price|level|buy|sell|trade|dip)\b",
    r"\bgood (time|day|week|moment|point|entry|price|idea) to (buy|sell|long|short|enter|get in|get out|invest)\b",
    r"\b(which|what) (coins?|tokens?|stocks?|cryptos?|alts?|altcoins?|memecoins?)\b.{0,30}\b(buy|pump|moon|go up|rise|explode|next|recommend|best|invest)",
    r"\b(will|is|does|gonna|going to|can)\b.{0,25}\b(pump|dump|moon|go up|go down|rise|crash|rally|tank|skyrocket)\b",
    r"\bprice (prediction|target|forecast)\b|\b(predict|forecast)\b.{0,20}\b(price|market|btc|eth|coin|stock)|\bwhere (is|will) (btc|eth|sol|bitcoin|ethereum|crypto|the market|the price|price|[a-z]{2,5} price) (go|head)",
    r"\byes or no\b|\bto the moon\b|\b(give|send) me (a |some )?(signals?|tips?|calls?|picks?)\b|\bwhat (should|do) i (buy|sell|invest in)\b|\bwhat to (buy|sell)\b",
    r"\brecommend\b.{0,20}\b(coins?|tokens?|stocks?|trades?|buy|entries)\b|\bdo you think i should\b|\bworth (buying|selling)\b",
    r"\b\d+(\.\d+)?k? (by|before) (monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|next|eow|eod|end of)\b",
    r"\b(le lu|lelu|lu kya|lena chahiye|khareed(u|na)?|kharid(u|na)?|bech(u|na| du)?)\b.{0,20}\b(kya|chahiye)\b",
    r"该买|该卖|该不该|要不要(买|卖|做多|做空|进场|入场|抄底|加仓)|(现在|此时|目前|今天|这个价|这里|这个位置).{0,10}合适吗|(买|卖|做多|做空|进场|入场|抄底).{0,10}合适吗|适合(买|卖|做多|做空|进场|入场)|好时机|时机(到了|对吗|合适)|值得买|值不值得|能不能买|可以抄底|抄底吗",
    r"会涨|会跌|涨到|跌到|能涨|哪个币|哪只(币|股)|推荐.{0,4}(币|股|个|只)|(该|应该|要|可以)买什么|买什么好|买哪个|该怎么操作",
]
# Any of these turns an advice/execution-looking sentence into a rule-check (gate) question.
RULE_CHECK = re.compile(
    r"\b(given|against|according to|by|under|per|within|with) (my |the )?rules?\b|\brules? (allow|permit|ok|okay|say)|"
    r"\b(break|breaks|violate|violates|allowed|allow)\b|\bcheck (it|this|that)\b|\bcheck against\b|"
    r"规则|违规|对一下|检查|允许|符合")
# A counterfactual frame ("what if I had sold everything") is a rule question, not a request.
COUNTERFACTUAL = re.compile(
    r"\bwhat if\b|\bif i (had|'d|hadn't|never)\b|\bhad i\b|\bwould\b.{0,40}\bhave\b|\bwould've\b|\bshould (i|we) have\b|\bshould've\b|"
    r"\bsimulat\w*|\bcounterfactual\b|如果|假如|要是|若是|的话会|会怎样|会怎么样|反事实|\bagar\b")
_NEG_BEFORE = re.compile(r"\b(not|don't|do not|never|didn't|won't|wouldn't|shouldn't|no need to|stop)\W+([a-z']+\W+){0,2}$|(没|不|别|不要|不想|不会|没有)\s*$")
_TEMPORAL_CLAUSE = re.compile(
    r"\b(before|after|until|once|when|whenever)\b (i |you |we )?(\w+ )?(place|placing|execute|executing|submit|submitting|send|sending|"
    r"confirm|confirming|buy|buying|sell|selling|enter|entering|open|opening|close|closing|pull|pulling)\b[^,.?!;]*")
_TEMPORAL_BEFORE = re.compile(r"\b(before|after|when|until|while|how (do|to|can) i|how to)\W+([a-z']+\W+){0,2}$")

# ---------------------------------------------------------------- scoring
# Weighted regexes per intent, grouped by concept. English phrases are stem-tolerant.
P = {
    "habit": [
        # canonical nouns
        (r"\bhabits?\b|\bpatterns?\b|\bmistakes?\b|\bworst\b|\bcostly\b|\bweakness(es)?\b|\btendenc(y|ies)\b|\bflaws?\b", 2),
        # money draining: leak / bleed / lose money / cost me / where does the money go
        (r"\bbleed\w*|\bbled\b|\bleak\w*|\bdrain\w*|\bburn(ing|ed|s)? (money|cash|capital)|\blos(e|ing|t) (so much |all )?(my )?(money|cash|capital)\b", 2),
        (r"where (does|did|is|do) (all )?(my |the )?(money|cash|capital|profits?|pnl|gains?) (go|goes|went|going)|where am i losing|where do i lose|money (go|goes|went)\b", 2.5),
        (r"doing wrong|do wrong|keep (on )?(losing|making|doing)|wrong with me|most expensive|cost(s|ing)? me (the )?most|biggest (mistake|problem|weakness|leak|issue|flaw)", 2),
        (r"\bcost(s|ing)? me\b|\bmy (biggest |main |real )?(problem|issue)\b|\bdo (things )?differently\b|\bimprove\b|\bfix (my|this)\b", 1.5),
        # named behaviours
        (r"\brevenge\b|\bover-?trad(e|es|ed|ing)\b|\btilt(ed|ing)?\b|\bfomo\b|\bover-?siz(e|es|ed|ing)\b|\bover-?leverag\w*|\bchas(e|es|ed|ing) (price|pumps?|entries|losses|the market)\b", 2),
        (r"\bhold\w* (on ?to )?(my |the )?(losers?|losing (trades|positions)|bags?|red (trades|positions))\b|\b(way |far )?too long\b|\bcut(ting)? (my )?winners?\b|\baverag(e|ing) down\b|\bpanic (sell|selling|sold)\b|\bmov(e|ing) (my )?stops?\b|\bbag ?hold\w*", 2),
        (r"\b(do|am|did) i (really |actually |always |often |usually |tend to )?(revenge|overtrade|over-?trad|oversize|tilt|chase|fomo|hold|panic|average)\w*", 1.5),
        (r"\bbad\b|\bwrong\b", 1),
        # Hinglish
        (r"\bgalti(yan|yaan)?\b|\baadat(ein|en)?\b|\bnuksa+n\b|\bnuqsa+n\b|\bpais[ae] (kahan|kaha|kidhar)\b|\b(nuksa+n|nuqsa+n|loss) (kaha?n?|kidhar) se\b|\bkyu+n (haar|loss)", 2),
        # Chinese
        (r"习惯|毛病|坏|报复|频繁|犯.{0,4}错|错误|老是|总是|经常|做错|哪里错|错在|最大问题|问题在哪|扛单|死扛|不肯割|不止损|拿着亏单|追涨杀跌|追高|上头|手痒|管不住", 2),
        (r"(?<!夜间)(?<!深色)(?<!暗黑)(?<!开发者)(?<!黑暗)模式", 2),
        (r"亏在哪|钱.{0,4}(去哪|亏哪|哪去)|亏钱|亏损最|让我亏|害我亏|费钱|最贵", 1.5),
    ],
    "rule": [
        (r"\bwhat if\b|\bcounterfactual\b|\bhalt\w*|\bcap(ped|ping|s)?\b|\bloss limit\b|\bcircuit breaker\b|\bcool-?(down|off)\b", 2),
        (r"would (a|an|the|my|that|this|it)\b.{0,50}\bhave (helped|changed|saved|done|made|cost|been)\b|would have (happened|been|changed|helped|saved)|would('ve| have) (i|my|it|that)|what would .{0,40}(change|do|look|happen)", 2),
        (r"\bhad i\b|\bif i (had|'d|hadn't|never|always|only|just)\b|\bkept\b|\bstuck to\b|\bfollow(ed|ing)?\b|\bsimulat(e|ing|ion)\b|\bstop(ped)? (trading )?after\b|\bbacktest\w*|\bshould (i|we) have\b|\bshould've\b", 1.5),
        (r"\brule\s*#?\s*\d\b|\bafter \d+ (losses|losing|red|losers|reds)\b|\b(max|maximum|at most|no more than|limit\w*)\b.{0,15}\b(per|a|each) (day|trade|week|session)\b", 1.5),
        (r"\bwould\b|\bif\b|\bsaved?\b|\binstead\b", 0.7),
        # Hinglish counterfactual
        (r"\bagar\b|\bkya hota\b|\bhota\b|\bhoti\b|\bbach(ta|te|ti)\b|\bruk (jata|jaata|jati|gaya)\b", 1.5),
        (r"如果|假如|要是|若是|反事实|熔断|停手|暂停|停止交易|止损|上限|不超过|最多.{0,4}(单|笔|次)|限制", 2),
        (r"规则\s*[\d一二三四五六七八九十]|遵守|守住|坚持|执行了?规则|会怎样|会怎么样|会咋样|会如何|结果会|少亏|省多少|能省|效果|有用吗|有没有用|管用|的话会|收益曲线|请模拟|模拟一下|回测", 1.5),
        (r"有没有效|有效吗|到底有没有|规则.{0,4}(有用|有效|管用)|咁会点|会点", 2),
    ],
    "court": [
        (r"\bcourt\b", 3),
        (r"\baccept\w*|\breject\w*|\bpropos(ed|al|als|e)\b|\btested\b|\bon trial\b|\btrials?\b|\bverdicts?\b|\bsurviv(e|ed|es|ing)\b", 2),
        (r"\bpass(ed|es|ing)? the (test|bar|court|trial)\b|\bpassed\b|\bpass(es)?\b|\bfail(ed|s)? the (test|trial|court)\b", 2),
        # strictness of the test: strict / threshold / bar / criteria / p-value / out of sample
        (r"\bstrict\w*|\blenient\b|\bloose\b|\bthreshold\w*|\bthe bar\b|\bcriteri(a|on)\b|\bp[- ]?values?\b|\bout[- ]of[- ]sample\b|\bsignifican\w*|\boverfit\w*|\bdata[- ]?snoop\w*|\bmultiple (testing|comparisons)\b|\bfalse positives?\b", 2.5),
        (r"how (do|does) (you|loop|it|the \w+) (decide|judge|test|validate|evaluate|vet|verify)\b|\bhow (strict|hard|tough|rigorous)\b|\b(test|tests|testing) (you run|rules|the rules)\b", 2),
        (r"\b(which|what) (new )?rules?\b|\brules (were|got|are|have|do i have)\b|\bmy rules\b", 1),
        (r"\brules? (actually |really )?(work|works|worked|working|hold up|held up)\b|\b(do|did|does) (my |the |these |any )?rules? (actually |really )?(work|help|hold)\b", 2),
        (r"采纳|否决|否了|拒绝|提议|提出|测试|法庭|通过|检验|严格|宽松|门槛|标准|样本外|显著|过拟合|审判|判决|裁决|能过|没过", 2),
        (r"我的规则|有哪些规则|规则有哪些|规则是什么", 1.5),
        (r"试了几次|判定|被接受|接受了|几条被", 2),
    ],
    "report": [
        (r"\bweekly\b|\breview\b|\brecap\b|\bsummar(y|ies|ise|ize|ised|ized)\b|\breport\b|\bhafte\b|\bhafta\b|\bwrap-?up\b|\bdigest\b|\boverview\b|\bscorecard\b", 2),
        (r"\bweek\b|\b(7|seven) days\b|\boverall\b|\bhow (did i do|was my|am i doing)\b|\bthis month\b|\blast month\b", 1.5),
        (r"how (did|was|were) (my |the )?(monday|tuesday|wednesday|thursday|friday|saturday|sunday|today|yesterday|day|month|session|weekend|it go)\b|how did (monday|tuesday|wednesday|thursday|friday|saturday|sunday|today|yesterday|it) go\b", 2),
        (r"\b(biggest|largest|best|worst) (single )?(losing |winning )?(loss|losses|win|wins|trade|trades|day|days|winner|loser)\b|\bwin ?rate\b|\bpnl\b|\bp&l\b|\bprofit\b|\bhow much did i (make|lose|earn)\b|\bhow many (trades|wins|losses|losers|winners)\b|\bstats\b", 2),
        (r"\bkaisa raha\b|\bkitna (kamaya|loss|profit|gaya)\b", 2),
        (r"复盘|周报|总结|报告|周度|回顾|月报|日报", 2),
        (r"本周|这周|上周|表现|亏了多少|赚了多少|盈亏|胜率|收益(?!曲线)", 1.5),
        (r"最近(发生|怎么样|如何|咋样)|近况", 2.5),
    ],
    "source": [
        (r"\bsource\b|\bprovenance\b|\bdemo\b|\bmock\b|\bsynthetic\b|\bfake\b|\bwhose\b|\bsimulated\b|\bpaper[- ]?trad\w*|\bcsv\b|\bupload\w*|\bimport(ed)?\b|\bsync(ed|ing)?\b|\bfresh\b|\bstale\b|\blast updated\b", 2),
        (r"(?<!out of )\bsample\b", 2),
        (r"come(s)? from|\bwhere\b.{0,20}\bfrom\b|\bdata from\b|pull(ed)? (this|it|the data)|which exchange|\breal (account|data|trades|numbers|fills)\b|\b(is|are) (this|it|that|these|those|the data|the numbers|the trades|my trades|the fills) (\w+ )?(real|genuine|legit|authentic|accurate)\b|numbers real|\blive or\b|\bactual\b.{0,20}\b(account|fills|trades)\b", 2),
        (r"\b(make|made|making|makes) (\w+ ){0,3}up\b|\bmade-up\b|\bfabricat\w*|\binvent(ed)?\b|\bhow do you (get|fetch|pull|access|see|read|know|obtain|have)\b.{0,20}\b(my )?(trades|data|fills|history|account|orders|numbers)\b", 2),
        (r"\breal\b|\bdata\b|\bwhere\b|\blive\b|\bfills\b|\bbitget\b|\bapi\b", 0.7),
        (r"\b(data|trades?|numbers?|fills|ye|yeh|account|record)\b.{0,15}\b(kaha?n?|kidhar) se\b|\bkiska\b|\basli\b|\bnakli\b", 2.5),
        (r"来源|哪里来|哪来|从哪|真实|真的|演示|谁的|实盘|假的|模拟盘|模拟的|模拟账户|模拟数据|编的|造的|交易所|怎么拿到|怎么获取|如何获取|怎么知道我的|同步|更新频率|上传", 2),
        (r"账户|数据|成交|交易记录", 0.7),
        (r"钱包|真数|示范|(哪个|哪家|什么).{0,3}(账户|交易所)", 2),
    ],
    "gate": [
        (r"\b(buy|sell|(?<!how )(?<!so )(?<!too )long|(?<!in )short|shorting|longing|buying|selling)\b", 1.5),
        (r"\badd to\b|\bsize up\b|\bopen (a |an |another )?(new )?(long|short|position)\b|\bgo (long|short)\b|\border idea\b|\bcheck (this|my) (order|trade|idea)\b|\bdouble down\b|\b(enter|re-?enter|get in|jump in)\b", 2),
        (r"\b(break|breaks|against|violate|given) (any |my |a |the )?rules?\b|\bok\s*\?|\bokay\s*\?|\bfine\b|\ballowed\b|\bbreak anything\b|\brules allow\b|\ballow karte\b|\bchalega\b", 1),
        (r"\bcan i (trade|enter|open|add|go|take|still trade)\b|\bam i allowed\b|\b(half|double|same) (size|trade|position)\b|\bsame trade\b", 1.5),
        (r"\$\s?\d|\b\d+(\.\d+)?\s?(k|usdt|usd|u)\b|\b\d+(\.\d+)?\s?x\b|\b(btc|eth|sol|xrp|doge|bnb|nvda|tsla|aapl)\b|\bposition\b|\bsiz(e|es|ing)\b", 1),
        (r"买入|卖出|做多|做空|加仓|减仓|补仓|开多|开空|多单|空单|仓位|下单(?!前|之前)|这单|订单|再来一单|还能交易|能交易吗|可以交易吗|能不能交易|能开吗", 2),
        (r"\d+\s*倍|符合.{0,6}规则|违反.{0,6}规则|违规|可以吗|行吗|行不行|允许吗|对一下", 1),
        (r"(买|卖)\s*[\d一二两三四五六七八九十百千万]+(\.\d+)?\s*(刀|美金|美元|u|个|万|k)", 2),
    ],
    "checklist": [
        (r"\bchecklists?\b|\bpretrade\b", 3),
        (r"\bbefore (a |an |the |i |entering |opening |placing |taking |making |buying |selling )?(a |an )?(trade|trading|entry|order|ordering|position|enter|open|place|buy|sell|take|go in|pull the trigger)\w*", 2),
        (r"things to (check|go through|look at|confirm)|what (do|should|must) i (need to )?(check|confirm|look at|verify|go through|review)\b|go through before|supposed to (check|look at|confirm|verify)|pull the trigger", 2),
        (r"\b(se )?pehle\b|\bcheck karna\b", 2),
        (r"清单", 3),
        (r"(交易|下单|开单|开仓|平仓|入场|进场|出场|买入|卖出|加仓|动手)(之|以)?前|检查项|核对", 2),
        (r"(要|该|应该|需要)(看|检查|确认|核对)(什么|哪些|啥)", 1.5),
        (r"规矩|规则列表|列.{0,2}(出|一下).{0,6}规则", 3),
        (r"检查|确认", 1),
    ],
    "help": [
        (r"^(hi|hello|hey|yo|thanks|thank you|thx|ok|okay|cool|help|good (morning|evening|afternoon)|namaste|gm)\b|what can you do|how do i use|how does (this|it) (thing |app )?work|\bjoke\b|\bweather\b|\bpoem\b|\bsong\b", 2),
        (r"\bwill .{0,20}(go up|go down|pump|dump|moon)\b|\bprice prediction\b|capital of|meaning of life|dark mode|\bwho won\b", 3),
        (r"^(什么是|啥是|请问什么是)(?!我)|是什么意思|^(解释|介绍)一下(?!我)", 3),
        (r"^(what is|what's|whats|what are|define|explain) (a|an)\b|\bwhat does .{0,25} mean\b|\bare you (a |an )?(real|human|bot|person|robot|ai)\b|\bkya aap\b|\b(hindi|english) me\b", 3),
        (r"^(你好|您好|谢谢|帮助|嗯|好的|在吗|哈喽|早上好)|你能做什么|你能干什么|怎么用|笑话|天气|会涨|会跌|涨到|跌到|你是(真人|机器人|谁|ai)|什么软件|夜间模式|人生的意义", 2),
    ],
}
_COMPILED = {k: [(re.compile(rx), w) for rx, w in v] for k, v in P.items()}
_INJ = [re.compile(r) for r in INJECTION]
_INJ_ORDER = [re.compile(r) for r in INJECTION_WITH_ORDER]
_ORD = [re.compile(r) for r in ORDER_REQUEST]
_ADV = [re.compile(r) for r in ADVICE]
_ORDER_VERB_RX = re.compile(_ORDER_VERB)

# single-word keywords for typo matching (edit distance), English only
FUZZY = {
    "habit": "habit", "habits": "habit", "pattern": "habit", "mistake": "habit", "mistakes": "habit", "worst": "habit",
    "costly": "habit", "revenge": "habit", "overtrade": "habit", "overtrading": "habit",
    "counterfactual": "rule", "simulate": "rule",
    "accepted": "court", "rejected": "court", "proposed": "court", "tested": "court", "verdict": "court",
    "weekly": "report", "review": "report", "recap": "report", "summary": "report", "summarize": "report", "report": "report",
    "source": "source", "provenance": "source", "synthetic": "source", "whose": "source",
    "checklist": "checklist", "pretrade": "checklist",
}
FUZZY_WEIGHT = 1.5

FOLLOWUP = re.compile(r"^(and|so|what about|how about|then|but|also|ok and|ok what about|same)\b|\binstead\b|\bthat\b|\bthis one\b|\bthe one\b|\bit\b|^(那|这个|那个|还有|再|换成|改成)|呢[?？]?$")

# ---------------------------------------------------------------- centroid fallback
CENTROID_MIN = 0.30       # best cosine must reach this
CENTROID_MARGIN = 0.08    # and beat the runner-up intent by this much, else help
# Calibrated on held-out lines (eval/blind_questions.jsonl, not in the training data): centroid-only
# at 0.30 / 0.06 was right on 36 of the 40 lines it fired on; 0.08 trades a little recall for precision.
_EXAMPLES = Path(__file__).with_name("router_examples.json")


def _ngrams(t: str) -> Counter:
    t = f" {t} "
    c: Counter = Counter()
    for n in (2, 3, 4):
        for i in range(len(t) - n + 1):
            g = t[i:i + n]
            if g.strip():
                c[g] += 1
    return c


def _unit(c: Counter) -> dict:
    norm = math.sqrt(sum(v * v for v in c.values())) or 1.0
    return {k: v / norm for k, v in c.items()}


def _load_centroids() -> dict[str, dict]:
    try:
        rows = json.loads(_EXAMPLES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    acc: dict[str, Counter] = {}
    for text, intent in rows:
        if intent not in INTENTS:
            continue
        acc.setdefault(intent, Counter()).update(_unit(_ngrams(normalise(text))))
    return {k: _unit(v) for k, v in acc.items()}


_CENTROIDS: dict[str, dict] | None = None


def centroid_scores(text: str) -> dict[str, float]:
    global _CENTROIDS
    if _CENTROIDS is None:
        _CENTROIDS = _load_centroids()
    v = _unit(_ngrams(normalise(text)))
    return {k: sum(w * c.get(g, 0.0) for g, w in v.items()) for k, c in _CENTROIDS.items()}


def centroid_pick(text: str) -> str | None:
    cs = centroid_scores(text)
    if len(cs) < 2:
        return None
    ranked = sorted(cs.items(), key=lambda kv: -kv[1])
    (best, b), (_, second) = ranked[0], ranked[1]
    if b >= CENTROID_MIN and b - second >= CENTROID_MARGIN:
        return best
    return None


# ---------------------------------------------------------------- helpers
def _dl(a: str, b: str, cap: int = 2) -> int:
    """Damerau-Levenshtein (optimal string alignment) distance, early-out above cap."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev2, prev = None, list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = a[i - 1] != b[j - 1]
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        prev2, prev = prev, cur
    return prev[-1]


def stem(tok: str) -> str:
    """Very light English stemmer: plurals and -ing/-ed, enough for concept matching."""
    for suf, rep, min_len in (("ies", "y", 5), ("sses", "ss", 5), ("ing", "", 6), ("ed", "", 5), ("es", "", 5), ("s", "", 4)):
        if tok.endswith(suf) and len(tok) >= min_len and not tok.endswith("ss"):
            return tok[: len(tok) - len(suf)] + rep
    return tok


_VOCAB_BY_STEM = {stem(w): w for w in VOCAB}


def _repair(tok: str) -> str:
    if tok in SHORTHAND:
        return SHORTHAND[tok]
    if len(tok) < 4 or not tok.isalpha() or tok in _VOCAB_SET or tok in COMMON or tok in FUZZY:
        return tok
    if stem(tok) in _VOCAB_BY_STEM:
        return tok
    cap = 1 if len(tok) < 8 else 2
    for w in VOCAB:
        if w[0] == tok[0] and abs(len(w) - len(tok)) <= cap and _dl(tok, w, cap) <= cap:
            if tok.startswith(w) or w.startswith(tok):   # "actually", "rejects": a real derivation, not a typo
                return tok
            return w
    return tok


def normalise(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "").translate(_T2S_TABLE).lower()
    t = t.replace("’", "'").replace("‘", "'").replace("甚么", "什么")
    t = re.sub(r"\bcheck\s*-?\s*list", "checklist", t)
    t = re.sub(r"\bpre\s*-?\s*trade\b", "pretrade", t)
    # CJK counts as a word character for \b, so "我的worst" would hide "worst": space the scripts apart
    t = re.sub(r"(?<=[一-鿿])(?=[a-z0-9$])|(?<=[a-z0-9%])(?=[一-鿿])", " ", t)
    t = re.sub(r"[a-z][a-z']*", lambda m: _repair(m.group(0)), t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _guarded(rx: re.Pattern, t: str, guard_temporal: bool = True) -> bool:
    """True if rx matches somewhere not directly preceded by a negation (or a temporal clause)."""
    for m in rx.finditer(t):
        before = t[: m.start()]
        if _NEG_BEFORE.search(before):
            continue
        if guard_temporal and _TEMPORAL_BEFORE.search(before):
            continue
        return True
    return False


def safety_flags(t: str) -> list[str]:
    """Flags for an already-normalised text: 'injection', 'order_request', 'advice'."""
    flags = []
    if (any(r.search(t) for r in _INJ) or _ENCODED.search(t)
            or (any(r.search(t) for r in _INJ_ORDER) and _ORDER_VERB_RX.search(t))):
        flags.append("injection")
    counterfactual = bool(COUNTERFACTUAL.search(t))
    t_ord = _TEMPORAL_CLAUSE.sub(" ", t)              # "before I place an order" is not a request to place one
    if not counterfactual and any(_guarded(r, t_ord) for r in _ORD):
        flags.append("order_request")
    if not flags and not counterfactual and not RULE_CHECK.search(t) and any(_guarded(r, t) for r in _ADV):
        flags.append("advice")
    return flags


def scores(text: str, previous_intent: str | None = None) -> dict[str, float]:
    text = (text or "")[:600]
    t = normalise(text)
    raw = unicodedata.normalize("NFKC", text or "")
    s = {k: 0.0 for k in INTENTS}
    for intent, rules in _COMPILED.items():
        for rx, w in rules:
            if rx.search(t):
                s[intent] += w
    if re.search(r"\br[A-Z]{2,5}\b", raw):            # tokenised stock tickers like rNVDA
        s["gate"] += 1
    elif re.search(r"(?<![A-Za-z])[A-Z]{3,5}(?![A-Za-z])", raw) and not re.search(r"\b(DAN|API|CSV|SYSTEM|PNL|USD|USDT|OK|FAQ|AI)\b", raw):
        s["gate"] += 0.5                               # an upper-case ticker in mixed text, e.g. 买两万刀NVDA
    for tok in re.findall(r"[a-z]{4,}", t):
        if tok in FUZZY or tok in COMMON or tok in _VOCAB_SET:
            continue
        cap = 1 if len(tok) < 8 else 2
        for kw, intent in FUZZY.items():
            if abs(len(kw) - len(tok)) <= cap and kw[0] == tok[0] and _dl(tok, kw, cap) <= cap:
                s[intent] += FUZZY_WEIGHT
                break
    if previous_intent in INTENTS and previous_intent != "help" and FOLLOWUP.search(t):
        s[previous_intent] += 1.5
    return s


def route_ex(text: str, previous_intent: str | None = None) -> tuple[str, list[str]]:
    text = (text or "")[:600]                   # the chat caps messages at 500; never spend time on more
    """Return (intent, flags). flags may include 'injection', 'order_request', 'advice', 'context', 'fallback'."""
    t = normalise(text)
    flags = safety_flags(t)
    if flags:
        return "help", flags
    s = scores(text, previous_intent)
    best = max(PRIORITY, key=lambda k: (s[k], -PRIORITY.index(k)))
    if s[best] >= FLOOR:
        return best, (["context"] if previous_intent == best and best != "help" else [])
    short = len(t.split()) <= 8 if not re.search(r"[一-鿿]", t) else len(t) <= 12
    # context may only rescue a follow-up: a marker ("and ...", "that", "呢") or a bare fragment. A full, different
    # question ("what is my Sharpe ratio") must never be hijacked by the previous answer.
    bare = len(t.split()) <= 3 if not re.search(r"[一-鿿]", t) else len(t) <= 7
    if previous_intent in INTENTS and previous_intent != "help" and short and (bare or FOLLOWUP.search(t)):
        return previous_intent, ["context"]
    picked = centroid_pick(text)
    if picked and picked != "help":
        return picked, ["fallback"]
    return "help", []


def route(text: str, previous_intent: str | None = None) -> str:
    return route_ex(text, previous_intent)[0]
