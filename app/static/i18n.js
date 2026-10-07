// EN / 中文 switch. English is the source text; Chinese is applied to text nodes by exact phrase or pattern.
// Anything not covered stays English (never guessed). Numbers are never touched.
const ZH_EXACT = {
  "■ No answer came back": "■ 没有收到回答", "Ask again": "再问一次", "too many questions at once; wait a moment.": "一次问得太多了；请稍等片刻。",
  "the service could not be reached. The numbers on the page are still correct.": "连不上服务。页面上的数字仍然是正确的。",
  "The numbers behind this": "这背后的数字", "Adjusted p": "校正后 p 值", "Real public data": "真实公开数据", "Your own data (as imported)": "你自己的数据（已导入）",
  "Simulated": "模拟", "Paper": "模拟盘", "Recorded Bitget book": "已记录的 Bitget 订单簿",
  "(report: all numbers computed from fills)": "（周报：所有数字都由成交记录计算）",
  "Rules that passed can be sent to your rulebook below and armed with one click.": "通过的规则可以发送到下方的规则手册，一键启用。",
  "Loop: trade review that tests its own rules": "Loop：先测试规则再信任的交易复盘", "Loop, home": "Loop，首页",
  "Sections of this page": "本页的各个部分", "Switch light or dark theme": "切换浅色或深色主题", "Choose a trader": "选择交易者",
  "The finding and the rule chart": "发现与规则图表", "Choose a rule": "选择规则", "Ask a question": "提问", "Rule to test": "要测试的规则", "Order idea": "下单想法",
  "Habit ratio per walk-forward window with 95% ranges": "每个滚动窗口的习惯比值及 95% 范围",
  "Cumulative profit and loss by trip, with and without the rule; the shaded part is trades the rule never saw": "按交易累计的盈亏，含规则与不含规则；阴影部分是规则没见过的交易",
  "These are intervals, not probabilities.": "这些是区间，不是概率。",
  "Finding": "发现", "Chart": "图表", "Court": "法庭", "Rulebook": "规则手册", "Costs": "成本", "Report": "报告",
  "The one finding": "唯一的发现", "Profit and loss, with and without the rule": "有规则与无规则的盈亏对比",
  "on trades the rule never saw": "在规则没见过的交易上", "over the whole history": "整段历史",
  "No habit passes the test for this trader.": "这位交易者没有习惯通过检验。",
  "That is a result, not a gap: the engine is meant to leave a trader alone when the data does not call for a rule.": "这是一个结果，不是缺口：数据不需要规则时，引擎本来就应该放过这位交易者。",
  "Tested within this trader's own fills, not against other people. The pre-declared cap rule prices it below.": "只在这位交易者自己的成交里检验，不与别人比较。事先声明的上限规则会在下方给它定价。",
  "On trades it never saw, the rule helped.": "在没见过的交易上，这条规则有帮助。",
  "On trades it never saw, the rule did not hold up.": "在没见过的交易上，这条规则没有站住。",
  "Not enough trades to judge this rule yet.": "交易还不够，暂时无法判断这条规则。",
  "median ratio,": "中位数比值，", "Rule: cap at 1.5x after a loss": "规则：亏损后上限 1.5 倍",
  "Could not reach the server. Nothing was changed; check your connection and try again.": "连不上服务器。没有任何改动；请检查网络后重试。",
  "Habit tests: result, effect size and adjusted p": "习惯检验：结果、效应大小与校正后 p 值", "Rule court: verdict on unseen trades": "规则法庭：在没见过的交易上的结论",
  "review that tests its own rules before you trust them": "先在没见过的交易上测试规则，再决定要不要信",
  "Read-only. No login. No key.": "只读。无需登录。无需密钥。",
  "Loading…": "加载中…", "Computing from fills…": "正在根据成交记录计算…",
  "In one look": "一眼看懂",
  "Profit and loss, with and without a rule": "有规则与无规则的盈亏对比",
  "What the rule would have changed": "这条规则会带来什么变化",
  "Rulebook and Rule Gate": "规则手册与规则闸门",
  "Check an order idea": "检查一个下单想法",
  "Ask about this trader": "询问这位交易者",
  "Habits found, each tested within this one trader": "发现的习惯，每一项都只在这位交易者自己的数据里检验",
  "Do your costs leave room? Required win rate at your real costs": "成本之后还有空间吗？按真实成本算的所需胜率",
  "Your checklist (most five stored, three shown)": "你的清单（最多存五项，显示三项）",
  "Apply rule:": "套用规则：", "Test it": "测试", "Check": "检查", "Ask": "提问",
  "halt for the day after 2 consecutive losing trips": "连续亏损 2 笔后当天停手",
  "cap opening size after a loss at 1.5x your median": "亏损后把开仓大小限制在你中位数的 1.5 倍",
  "Grey: what happened. Teal: what would have happened with the rule. Net of fees.": "灰线：实际发生的。青线：套用规则后会发生的。已扣手续费。",
  "on the trades it was built from": "在用来建立规则的交易上", "on trades it never saw": "在它没见过的交易上",
  "Size after a loss": "亏损后的开仓大小", "Holding losers longer than winners": "亏损单比盈利单拿得更久",
  "Trading more on your busiest days": "最忙的日子交易更多", "Re-entering the same symbol soon after a loss": "亏损后很快在同一品种再次进场",
  "What is my biggest costly habit?": "我最大的坏习惯是什么？", "What if I had kept rule 2?": "如果我遵守规则 2 会怎样？", "Show my weekly review": "给我看这周的复盘",
  "The rule's parameter was fixed before looking at this history. The effect may be small or negative; it is shown as it is.": "规则的参数在看这段历史之前就定好了。效果可能很小，也可能是负的；如实显示。",
  "＋ Import your history": "＋ 导入你自己的记录", "Review your own history": "复盘你自己的记录", "Review it": "开始复盘",
  "Habit": "习惯", "Result": "结果", "Size of effect": "效应大小", "Range (95%)": "范围（95%）", "Trades in each group": "每组交易数",
  "Rule": "规则", "Verdict": "结论", "Effect on unseen trades": "对没见过的交易的影响", "Trades it touched": "涉及的交易", "Bar to clear": "要跨过的门槛",
  "▲ habit found": "▲ 发现习惯", "◌ could not check": "◌ 无法检查", "● nothing found": "● 没发现", "◌ not enough trades yet": "◌ 交易还不够",
  "✔ accepted": "✔ 通过", "✖ rejected": "✖ 未通过", "✔ accepted, waiting for you": "✔ 已通过，等你确认", "● armed": "● 已启用",
  "▲ pending retirement": "▲ 待退役", "○ retired": "○ 已退役", "✖ quarantined": "✖ 已隔离",
  "✔ checks passed": "✔ 检查通过", "▲ passed with notes": "▲ 通过但有提示", "✖ review needed": "✖ 需要复核", "■ blocked by your rules": "■ 被你的规则拦下",
  "Arm this rule": "启用这条规则", "Propose retirement": "提出退役", "Confirm retirement": "确认退役", "Keep it": "保留",
  "Send a rule to the court:": "把一条规则送去法庭：",
  "my last trade was a loss (otherwise taken from the record)": "我上一笔是亏损（否则按记录判断）",
  "Every proposal is counted, so the bar for acceptance rises with each rule tried.": "每个提案都会计数，所以试得越多，通过的门槛越高。",
  "Your own sandbox: nothing here places an order, and it resets when your session ends. A rule only guards your orders after you click Arm.": "这是你自己的沙盒：这里不会下任何单，会话结束就重置。规则只有在你点击“启用”之后才会拦你的下单。",
  "win rate you need to break even": "盈亏平衡所需胜率", "win rate you have": "你现有的胜率",
  "No rules yet. Send one to the court; only a rule that passes on unseen trades can be armed.": "还没有规则。送一条去法庭；只有在没见过的交易上通过的规则才能启用。",
  "No checklist items yet: they come from habits that pass the test and from rules you arm.": "还没有清单项目：它们来自通过检验的习惯和你启用的规则。",
  "Every number on this page is computed from fills when you load it; none is typed by hand. A flagged habit is a pattern in the data, not a judgement of the person. Rules are tested on trades they were not learned from, and \"underpowered\" means the honest answer is \"not enough trades yet\".":
    "页面上每个数字都是加载时由成交记录计算的，没有手填的。被标出的习惯是数据里的模式，不是对人的评价。规则在它没学过的交易上测试；“样本不足”意味着诚实的答案是“交易还不够”。",
};
const ZH_PATTERNS = [
  [/^cap opening size at ([\d.]+)x your median after a loss:$/, "亏损后开仓大小上限为你中位数的 $1 倍："],
  [/^(ACCEPTED|REJECTED|UNDERPOWERED)$/, (m, k) => ({ ACCEPTED: "通过", REJECTED: "未通过", UNDERPOWERED: "样本不足" })[k]],
  [/^SIMULATED trader, built on purpose with a costly habit to show what an accepted rule looks like\. Not a real person\. \((\w+)\)$/, "模拟交易者：特意设置有代价的习惯，用来展示通过的规则长什么样。不是真人。（$1）"],
  [/^the service answered (\d+)\. The numbers on the page are still correct\.$/, "服务返回了 $1。页面上的数字仍然是正确的。"],

  [/^Single order is within (\d+)% of visible depth within ([\d.]+) bps\.$/, "单笔订单在 $2 个基点内可见深度的 $1% 以内。"],
  [/^Split into (\d+) children of ([\d,.]+) USDT \(each <= (\d+)% of visible depth\)\.$/, "拆成 $1 笔子单，每笔 $2 USDT（各不超过可见深度的 $3%）。"],
  [/^Weekday rToken cost cannot be validated from the public tape \(no public weekday prints\)\.$/, "工作日 rToken 的成本无法用公开成交记录验证（没有公开的工作日成交）。"],
  [/^(\w+)USDT perp funding averaged (-?[\d.]+) bp per interval on the trade day \((\d+) settlements\)\.$/, "$1USDT 永续合约的资金费在交易当天平均每个间隔 $2 个基点（$3 次结算）。"],
  [/^I could not read a dollar order size from that \(a number followed by x is leverage, not a size\), so nothing was checked\. Give the size in USDT, for example (.*)\.$/, "我没读到美元下单大小（数字后面跟 x 是杠杆，不是大小），所以什么都没检查。请用 USDT 给出大小，例如 $1。"],
  [/^A size rule is armed but I could not read an order size, so I cannot check this idea: tell me the size, for example (.*)\.$/, "你启用了大小规则，但我没读到下单大小，所以无法检查这个想法：请告诉我大小，例如 $1。"],
  [/^You gave a quantity \(([\d.,]+) (.*)\), not a dollar size, and I have no recent book price for (.*) to convert it, so nothing was checked\. Give the size in USDT, for example (.*)\.$/, "你给的是数量（$1 $2），不是美元大小，而且我没有 $3 的最新盘口价格来换算，所以什么都没检查。请用 USDT 给出大小，例如 $4。"],
  [/^(upward|downward) drift \((habit growing|habit shrinking)\) · (\S+) · (.*)$/, (m, a, b, d, v) => (a === "upward" ? "向上漂移（习惯在加重）" : "向下漂移（习惯在减轻）") + " · " + d + " · " + v],
  [/^Numbers locked: (refused.*)$/, "数字已锁定：已拒绝（$1）"],
  [/^\(report: all numbers computed from fills\)$/, "（周报：所有数字都由成交记录计算）"],
  [/^Interpreted as: (.*)$/, "理解为：$1"],
  [/^win rate you need to break even \(95% range (.*) to (.*)\)$/, "盈亏平衡所需胜率（95% 范围 $1 到 $2）"],
  [/^win rate you have; gap range (.*) to (.*)$/, "你现有的胜率；差距范围 $1 到 $2"],
  [/^Real Bitget futures export \(website CSV\) published publicly by its owner.*$/, "真实的 Bitget 合约导出文件（网站 CSV），由其所有者公开发布（GPL-3.0 数据，一个交易机器人的账户，不是本项目所有者的账户）。这种导出格式不含开仓手续费，所以净结果比实际偏高。"],
  [/^Public Hyperliquid wallet, hand-picked, illustrative\. Not a Bitget user and not the owner's account\.$/, "公开的 Hyperliquid 钱包，人工挑选，仅作示例。不是 Bitget 用户，也不是项目所有者的账户。"],
  [/^Check line: about (.*) bps versus mid$/, "检查线：相对中间价约 $1 个基点"],
  [/^Check line$/, "检查线"],
  [/^Bitget context \(not evidence\)$/, "Bitget 背景信息（不是证据）"],
  [/^Bitget context$/, "Bitget 背景信息"],
  [/^Read: (\S+) (\S+) (.*?); last trade (was a loss|was not a loss)\.$/, (m, a, b, c, d) => "读到：" + (a === "buy" ? "买入" : a === "sell" ? "卖出" : a) + " " + b + " " + c.replace("(no size found)", "（没读到大小）") + "；上一笔" + (d === "was a loss" ? "是亏损" : "不是亏损") + "。"],
  [/^(\S+) (REAL_\w+|SIM_\w+|REPLAY_\w+); book (\d+) s old(.*)$/, "$1 $2；订单簿是 $3 秒前的$4"],
  [/^This checks an idea against your own rules\. It does not place, preview or route any order\.$/, "这里只是对照你自己的规则检查一个想法，不会下单、预览或路由任何订单。"],
  [/^I could not read an order size, so size rules were not checked\.$/, "我没读到下单大小，所以没有检查大小规则。"],
  [/^I could not read a symbol or an order size from that, so nothing was checked\. Try: (.*)$/, "我没读到品种或下单大小，所以什么都没检查。试试：$1"],
  [/^Rule (\S+): your last trade lost and this idea \(([\d,]+)\) is above the cap \(([\d,]+)\)\.$/, "规则 $1：你上一笔亏了，而这个想法（$2）超过了上限（$3）。"],
  [/^Estimated execution cost is (.*) bps on the live book\.$/, "按实时订单簿估算，执行成本约 $1 个基点。"],
  [/^The visible book absorbs only (\d+)% of this size; the rest is not assumed to clear\.$/, "可见订单簿只能吃下这个大小的 $1%；其余部分不假设能成交。"],
  [/^No Bitget skill answered just now\.$/, "刚才没有 Bitget 技能响应。"],
  [/^([\d,]+) fills → ([\d,]+) orders → ([\d,]+) round trips$/, "$1 笔成交 → $2 笔订单 → $3 个完整交易"],
  [/^On trades it never saw, the rule did not hold up\. held-out effect is not positive\.?$/, "在没见过的交易上，这条规则没有站住：未见交易上的效果不是正的。"],
  [/^n=(\d+) broke it, (\d+) kept it; keeping it did (better|worse) by (.*) per trade \(p=(.*)\)(.*)$/, "$1 笔违反、$2 笔遵守；遵守的结果$3 $4 每笔（p=$5）$6"],
  [/^not enough trades yet: (.*)$/, "交易还不够：$1"],
  [/^Every number on this page is computed from fills when you load it.*$/, "页面上每个数字都是加载时由成交记录计算的，没有手填的。被标出的习惯是数据里的模式，不是对人的评价。规则在它没学过的交易上测试；“样本不足”意味着诚实的答案是“交易还不够”。"],
  [/^Rule court: (\d+) rules proposed, (\d+) tested, (\d+) accepted$/, "规则法庭：提出 $1 条，测试 $2 条，通过 $3 条"],
  [/^Rule court: (\d+) proposed, (\d+) tested, (\d+) accepted on unseen trades\. (.*)$/, (m, a, b, c, d) => "规则法庭：提出 " + a + " 条，测试 " + b + " 条，在没见过的交易上通过 " + c + " 条。" + (TAIL[d] || d)],
  [/^A rule that passed is waiting for you to arm it, below\.$/, "有一条通过的规则在下方等你启用。"], [/^No rule has earned arming yet\.$/, "目前没有规则值得启用。"],
  [/^: ([\d.]+)x, range ([\d.]+) to ([\d.]+) \(p=([\d.]+)\)\. Capping size at 1\.5x your median would have changed$/, "：$1 倍，范围 $2 到 $3（p=$4）。把开仓大小限制在你中位数的 1.5 倍，会让结果变化"],
  [/^over this whole history \(range (.*) to (.*)\) and$/, "（整段历史，范围 $1 到 $2），在规则没见过的交易上变化"],
  [/^on trades the rule never saw\.$/, "。"],
  [/^: No habit passes the test.*$/, "没有习惯通过检验，这是一个结果，不是缺口。"],
  [/^on trades it never saw \((\d+) skipped\)$/, "在它没见过的交易上（跳过 $1 笔）"],
  [/^On trades it never saw, the rule did not hold up\. held-out effect is not positive$/, "在没见过的交易上，这条规则没有站住：未见交易上的效果不是正的"],
  [/^On trades it never saw, the rule helped\. (.*)$/, "在没见过的交易上，这条规则有帮助。$1"],
  [/^Not enough trades to judge this rule yet: (.*)$/, "交易还不够，暂时无法判断这条规则：$1"],
  [/^cap at ([\d.]+)x median$/, "上限为中位数的 $1 倍"],
  [/^cap opening size at ([\d.]+)x your median after a loss$/, "亏损后开仓大小上限为你中位数的 $1 倍"],
  [/^Last trade lost: is this order bigger than your usual size\?$/, "上一笔亏损了：这笔订单是否比你平常的仓位更大？"],
  [/^Write the exit for a losing trade before you enter\.$/, "进场之前先写好亏损单的退出条件。"],
  [/^win rate you need to break even \(95% range (.*) to (.*)\)$/, "盈亏平衡所需胜率（95% 范围 $1 到 $2）"],
  [/^win rate you have; gap range (.*) to (.*)$/, "你现有的胜率；差距范围 $1 到 $2"],
  [/^Without your single best trade the break-even win rate is (.*?)\. (.*)These are intervals, not probabilities\.$/, (m, a, b) => "去掉你最好的一笔交易后，盈亏平衡胜率是 " + a + "。" + b.replace(/Fees took (.*) of gross profit \(range (.*) to (.*)\)\./, "手续费占毛利润的 $1（范围 $2 到 $3）。") + "这些是区间，不是概率。"],
  [/^rule learned on this part$/, "规则在这一段上建立"], [/^tested on trades it never saw$/, "在没见过的交易上测试"],
  [/^held-out effect is not positive$/, "未见交易上的效果不是正的"],
  [/^(\d+) fills → (\d+) orders → (\d+) round trips$/, "$1 笔成交 → $2 笔订单 → $3 个完整交易"],
  [/^simulated, (\d+) round trips$/, "模拟数据，$1 个完整交易"],
  [/^(\d+) rules proposed so far \(every proposal counts\) · event log (.*) · (\d+) events$/, "目前已提出 $1 条规则（每个提案都计数）· 事件日志 $2 · $3 个事件"],
  [/^Public Hyperliquid wallet, hand-picked, illustrative\. Not a Bitget user and not the owner's account\.$/, "公开的 Hyperliquid 钱包，人工挑选，仅作示意。不是 Bitget 用户，也不是所有者的账户。"],
  [/^SIMULATED trader, built on purpose with a costly habit to show what an accepted rule looks like\. Not a real person\.$/, "模拟交易者：特意设置了一个有代价的习惯，用来展示通过的规则长什么样。不是真人。"],
  [/^Wallet ([A-Z])$/, "钱包 $1"], [/^ · control$/, " · 对照组"], [/^(.*) · (\d+) trips$/, (m, a, n) => (BLURB[a] || a) + " · " + n + " 笔交易"],
  [/^Stock-perp trader the engine should leave alone$/, "引擎应该放过的股票永续交易者"], [/^Sizes up after losses \(the one flag that passes the test\)$/, "亏损后加大仓位（唯一通过检验的标记）"],
  [/^Suggestive size pattern, not proven$/, "有提示但未证实的仓位模式"], [/^Long, steady history$/, "长期、稳定的历史"], [/^No size or hold habit found$/, "没发现仓位或持仓习惯"],
  [/^SIMULATED trader built to have a costly habit: shows the court's accept path$/, "模拟交易者：特意设置有代价的习惯，用来展示法庭的“通过”路径"],
  [/^Interpreted as: (.*)$/, "理解为：$1"], [/^Numbers locked: every number comes from a computed fact$/, "数字已锁定：每个数字都来自计算出的事实"],
  [/^Language model: (.*)$/, "语言模型：$1"], [/^on the trades it was built from \((\d+) trips skipped\)$/, "在用来建立规则的交易上（跳过 $1 笔）"],
  [/^from \((\d+) trips skipped\)$/, "（跳过 $1 笔）"],
];
const BLURB = {
  "Stock-perp trader the engine should leave alone": "引擎应该放过的股票永续交易者",
  "Sizes up after losses: suggestive, not proven": "亏损后加大仓位：有提示但未证实",
  "A REAL Bitget futures export (public, a trading bot's DOGE trades), read by our Bitget CSV importer": "真实的 Bitget 合约导出文件（公开，一个交易机器人的 DOGE 交易），由我们的 Bitget CSV 读取器读取",
  "Suggestive size pattern, not proven": "有提示但未证实的仓位模式", "Long, steady history": "长期、稳定的历史",
  "No size or hold habit found": "没发现仓位或持仓习惯",
  "SIMULATED trader built to have a costly habit: shows the court's accept path": "模拟交易者：特意设置有代价的习惯，用来展示法庭的“通过”路径",
};
const TAIL = { "No rule has earned arming yet.": "目前没有规则值得启用。", "A rule that passed is waiting for you to arm it, below.": "有一条通过的规则在下方等你启用。" };
let LANG = "en";
try { LANG = localStorage.getItem("lang") || "en"; } catch (e) {}
const _orig = new Map();
const CAPZ = String.raw`Capping your opening size at ([\d.]+)x your usual after a loss`;
const HABIT_ZH = {
  "A size habit passes the test within this trader.": "这位交易者自己的数据里，有一个仓位习惯通过了检验。",
  "A size habit looks real on its own but does not survive the correction for the several habit tests run, so it is not called a habit.": "仓位习惯单看像是真的，但经过对多次习惯检验的校正后站不住，所以不把它称为习惯。",
  "No habit passes the test for this trader.": "这位交易者没有习惯通过检验。",
};
const PLAIN_RULES = [
  [new RegExp("^" + CAPZ + String.raw` would have saved (-?\$[\d,]+) on trades it never saw, and the court accepted that rule( on that evidence alone, without calling it a habit)?: send it to your rulebook and click Arm to use it\.$`),
    (m, n, d, alone) => "亏损后把开仓大小限制在你平时的 " + n + " 倍，在没见过的交易上本可以省下 " + d + "，法庭" + (alone ? "仅凭这一证据就通过了这条规则，并没有称它为习惯" : "通过了这条规则") + "：把它送到你的规则手册，点击“启用”即可使用。"],
  [/^There are not enough trades yet to judge any rule for this trader: the court needs at least 30 unseen trades and a rule that touches at least 10 of them\.$/, "这位交易者的交易还不够，暂时无法判断任何规则：法庭至少需要 30 笔没见过的交易，并且规则要涉及其中至少 10 笔。"],
  [new RegExp("^" + CAPZ + String.raw` looks positive on unseen trades \((-?\$[\d,]+)\) but not by enough to rule out luck, so the court did not accept it\.$`),
    (m, n, d) => "亏损后把开仓大小限制在你平时的 " + n + " 倍，在没见过的交易上看起来是正的（" + d + "），但幅度不足以排除运气，所以法庭没有通过。"],
  [new RegExp("^" + CAPZ + String.raw` would have changed (-?\$[\d,]+) on trades it never saw, so the court did not accept it\.$`),
    (m, n, d) => "亏损后把开仓大小限制在你平时的 " + n + " 倍，在没见过的交易上会让结果变化 " + d + "，所以法庭没有通过。"],
];
function plainZh(t) {
  const m = /^(A size habit passes the test within this trader\.|A size habit looks real on its own but does not survive the correction for the several habit tests run, so it is not called a habit\.|No habit passes the test for this trader\.)( Separately, | )(.*)$/.exec(t);
  if (!m) return null;
  let rest = m[3], tail = "";
  const tl = /^(.*?)( (\d+) of the (\d+) caps the court tested were accepted; see the court table\.)$/.exec(rest);
  if (tl) { rest = tl[1]; tail = " 法庭测试的 " + tl[4] + " 个上限里有 " + tl[3] + " 个通过了；见法庭表格。"; }
  for (const [rx, rep] of PLAIN_RULES) if (rx.test(rest)) return HABIT_ZH[m[1]] + (m[2] === " Separately, " ? "另外，" : "") + rest.replace(rx, rep) + tail;
  return null;
}
const STEP_ZH = [
  [/^read question \(safety check\)$/, "读取问题（安全检查）"], [/^read question \(keywords\)$/, "读取问题（关键词）"],
  [/^read question \(deterministic parser\)$/, "读取问题（确定性解析）"], [/^read question$/, "读取问题"],
  [/^loaded (\d+) round trips, computed (\S+) on (\d+)$/, "载入 $1 个完整交易，对 $3 笔计算 $2"], [/^loaded (\d+) round trips$/, "载入 $1 个完整交易"],
  [/^number-lock: every number backed \((\w+)\)$/, (m, k) => "数字锁：每个数字都有依据（" + (k === "passed" ? "通过" : k) + "）"],
  [/^guard: question outside the closed schema$/, "防护：问题超出封闭的查询范围"], [/^Qwen planner \(schema-validated\)$/, "Qwen 规划器（经过格式校验）"],
];
function stepsZh(t) {
  if (!/ ms( › |$)/.test(t)) return null;
  const parts = t.split(" › ");
  const out = [];
  for (const p of parts) {
    const m = /^(.*) ([\d.,]+) ms$/.exec(p);
    if (!m) return null;
    let name = null;
    for (const [rx, rep] of STEP_ZH) if (rx.test(m[1])) { name = m[1].replace(rx, rep); break; }
    if (name === null) return null;
    out.push(name + " " + m[2] + " 毫秒");
  }
  return out.join(" › ");
}
function zhCore(t) {
  if (ZH_EXACT[t]) return ZH_EXACT[t];
  if (BLURB[t]) return BLURB[t];
  const pz = plainZh(t); if (pz) return pz;
  const sz = stepsZh(t); if (sz) return sz;
  for (const [rx, rep] of ZH_PATTERNS) if (rx.test(t)) return t.replace(rx, rep);
  return null;
}
function zhOf(txt) {
  const t = txt.trim().replace(/\s+/g, " ");
  if (!t) return null;
  const z = zhCore(t);
  if (z === null) return null;
  return txt.match(/^\s*/)[0] + z + txt.match(/\s*$/)[0];        // a text node may hold inner newlines: keep only the outer whitespace
}
function translateTree(root) {
  const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = w.nextNode())) {
    if (LANG === "zh") {
      if (!_orig.has(n)) { const z = zhOf(n.nodeValue); if (z) { _orig.set(n, n.nodeValue); n.nodeValue = z; } }
    }
  }
  root.querySelectorAll("[aria-label],[title]").forEach((el) => {
    for (const a of ["aria-label", "title"]) {
      const v = el.getAttribute(a); if (!v) continue;
      const k = "en" + a.replace("-", "");
      if (LANG === "zh") { if (el.dataset[k] === undefined) { const z = zhCore(v.trim().replace(/\s+/g, " ")); if (z) { el.dataset[k] = v; el.setAttribute(a, z); } } }
      else if (el.dataset[k] !== undefined) { el.setAttribute(a, el.dataset[k]); delete el.dataset[k]; }
    }
  });
  root.querySelectorAll("[placeholder]").forEach((el) => {
    if (!el.dataset.en) el.dataset.en = el.placeholder;
    el.placeholder = LANG === "zh" ? (el.dataset.en.startsWith("Ask in English") ? "用中文或 English 提问，例如：我最大的坏习惯是什么？" : el.dataset.en.startsWith("e.g.") ? "例如：买 2万 rNVDA" : el.dataset.en) : el.dataset.en;
  });
}
function setLang(l) {
  LANG = l;
  try { localStorage.setItem("lang", l); } catch (e) {}
  if (l === "en") { _orig.forEach((v, n) => { if (n.isConnected) n.nodeValue = v; }); _orig.clear(); }
  translateTree(document.body);
  document.documentElement.lang = l === "zh" ? "zh-CN" : "en";
  try { if (!window.__enTitle) window.__enTitle = document.title; document.title = l === "zh" ? (zhCore(window.__enTitle) || window.__enTitle) : window.__enTitle; } catch (e) {}
  const b = document.getElementById("langbtn"); if (b) b.textContent = l === "zh" ? "English" : "中文";
}
let _busy = false;
new MutationObserver(() => { if (_busy || LANG !== "zh") return; _busy = true; translateTree(document.body); _busy = false; })
  .observe(document.body, { childList: true, subtree: true, characterData: false });
window.addEventListener("DOMContentLoaded", () => { setLang(LANG); });
// wired here, not as an onclick attribute: the Content-Security-Policy runs no inline handlers
{ const lb = document.getElementById("langbtn"); if (lb) lb.addEventListener("click", () => setLang(LANG === "zh" ? "en" : "zh")); }
// status strip, /wrong, /proof, skills panel (appended; exact phrases only)
Object.assign(ZH_EXACT, {
  "Sources": "数据源", "Public record": "公开记录", "live": "在线", "stale": "过期", "off": "关闭", "broken": "已损坏",
  "Bitget order-book cache": "Bitget 订单簿缓存", "Bitget public market calls": "Bitget 公开行情调用", "UTA importer (Bitget API fills)": "UTA 导入器（Bitget API 成交）",
  "CSV importer (Bitget export, Hyperliquid fills)": "CSV 导入器（Bitget 导出、Hyperliquid 成交）", "Loop MCP server (read-only)": "Loop MCP 服务（只读）",
  "Qwen intent helper": "Qwen 意图助手", "Hash chain verify": "哈希链校验",
  "user decisions": "用户决定", "sandbox, judge and test decisions": "沙盒、评审和测试决定", "rules armed": "已启用规则", "rules retired": "已退役规则", "rules rejected": "被否决规则",
  "What we got wrong": "我们的错误", "Verify the record": "校验记录", "Proof": "证明", "Back to the review": "返回复盘",
  "Loop: what we got wrong": "Loop：我们的错误", "Loop: proof": "Loop：证明", "Proof, measured": "实测证明",
  "Every rejected or retired rule, every planted-suite miss and every chat-router miss, kept in the open.": "每一条被否决或退役的规则、每一次植入测试的失误、每一次聊天路由的失误，全部公开。",
  "What the court does on planted traders and a public cohort, and how it compares with naive checks. Misses are kept.": "法庭在植入交易者和公开样本上的表现，以及与朴素检验的对比。失误全部保留。",
  "Every number on this page is read from a results file or the record log when you load it; none is typed by hand.": "本页每个数字都在加载时从结果文件或记录日志读取，没有手填的。",
  "Rules the court rejected or retired (public record)": "法庭否决或退役的规则（公开记录）", "Planted-suite misses (simulated traders)": "植入测试的失误（模拟交易者）",
  "Court cells above its own bar": "高于法庭自身门槛的格子", "Chat router misses": "聊天路由的失误", "Cohort: every rule the court tried on 60 wallets": "样本：法庭在 60 个钱包上试过的每条规则",
  "The court: measured wrong acceptance and power": "法庭：实测错误通过率与检出力", "The 60-wallet cohort": "60 个钱包的样本", "Chat router question sets": "聊天路由问题集",
  "Naive in-sample check against the court (planted suite)": "朴素样本内检验与法庭对比（植入测试）",
  "Rule size (x median)": "规则大小（中位数的倍数）", "Rejected": "未通过", "Underpowered": "样本不足", "Accepted": "通过", "When": "时间", "Trader": "交易者", "Rule": "规则",
  "What happened": "发生了什么", "Reason": "原因", "Cell": "格子", "What": "内容", "Count": "数量", "Rate": "比例", "Wrong acceptance": "错误通过",
  "Question": "问题", "Should be": "应为", "Routed to": "被路由到", "Set": "问题集", "Label": "标签", "Questions": "问题数", "First scoring": "首次评分", "Now": "现在",
  "Truth": "真实情况", "Naive: would have saved money": "朴素：本来能省钱", "Naive: p below 0.05": "朴素：p 值低于 0.05", "Court accepts": "法庭通过",
  "Situation": "情形", "Trades": "交易数", "Not enough trades to judge": "交易太少无法判断",
  "No leak at all": "完全没有漏损", "A habit that costs nothing extra": "没有额外代价的习惯", "A real costly leak": "真实有代价的漏损",
  "nothing there": "什么都没有", "real leak": "真实漏损", "leak that faded": "已消退的漏损", "Every miss": "全部失误",
  "author-blind": "作者自测盲集", "tuned": "已调优", "tuned-after-first-score": "首次评分后已调优",
  "Skills: what each public Bitget call returned": "技能：每个 Bitget 公开调用返回了什么", "Order-ticket preview": "下单票据预览",
  "Source": "来源", "Call": "调用", "Status": "状态", "Timing": "耗时", "Answered": "已回答", "State": "状态",
  "Loading the skills panel…": "正在加载技能面板…", "Loading…": "加载中…",
});
// /runs board (appended; exact phrases only)
Object.assign(ZH_EXACT, {
  "Loop: daily runs": "Loop：每日运行", "Daily runs": "每日运行",
  "One prediction per trader per day, frozen in a hash chain that is only ever appended to. Scored after 24 hours; misses stay on the board.": "每位交易者每天一条预测，冻结在只增不改的哈希链里。24 小时后评分；失误会一直留在榜上。",
  "Every row is read from the chain when you load it.": "每一行都是在你打开页面时从链上读取的。",
  "Frozen": "冻结时间", "Prediction": "预测", "Hash": "哈希", "pending": "待定", "scored": "已评分", "missed": "失误",
  "No runs have been frozen yet.": "还没有冻结任何运行。", "The runs could not be loaded. Nothing on this page is guessed.": "无法加载运行记录。本页没有任何猜测。",
  "rule and cost use live data; reproduce is a replay of the engine on the frozen day.": "rule 和 cost 使用实时数据；reproduce 是在冻结当天对引擎的重放。",
  "Daily runs (frozen predictions)": "每日运行（冻结的预测）",
  "Chasing a big prior move": "大幅波动之后顺势追单", "Trading stock perps outside US cash-session hours": "美股常规交易时段之外交易股票永续", "Adding at a worse price (averaging down)": "在更差的价格上加仓（摊平）",
});
