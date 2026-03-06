#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import random
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable


SEED = 20260226
BATCH_COUNT = 10
BATCH_SIZE = 100
CANDIDATE_PER_BATCH = 120

OUTPUT_DIR = Path(".")
BATCH_FILE_TMPL = "qwen25_7b_lpg_train_data_batch_{:02d}.jsonl"
MERGED_FILE = "qwen25_7b_lpg_train_data_1000.jsonl"

TERMS = [
    "角阀",
    "减压阀",
    "残液",
    "气化速度",
    "检验标识",
    "追溯码",
    "软管",
    "瓶阀",
    "回火",
    "黄火",
]

EMPATHY = [
    "我太理解您的心情了，先别慌，我陪您一步一步处理。",
    "您这个着急我完全能理解，咱们先把风险降到最低。",
    "辛苦您先稳住，我先给您最关键、最安全的处理顺序。",
    "您先别自责，这种情况最重要的是先保人身安全。",
    "我理解您现在很焦虑，先按我这几步来，能最快控住风险。",
]

EMPATHY_ORDER = [
    "我太理解您一直等气的着急了，我马上按加急流程帮您推进。",
    "辛苦您催单了，您的时间很宝贵，我这边给您明确处理时点。",
    "您这边着急做饭我完全理解，我先把进度和下一步说清楚。",
    "让您久等确实不应该，我先给您一个可执行的解决路径。",
]

EMPATHY_PRICE = [
    "我理解您对费用的敏感，这笔钱我给您讲清楚每一项依据。",
    "您提得很对，费用问题必须透明，我按政策给您逐条说明。",
    "辛苦您反馈，咱们把争议点拆开核对，避免您多跑冤枉路。",
]

EMPATHY_TECH = [
    "您描述得很准确，我用最通俗的话给您讲清原理和处理顺序。",
    "我理解您担心设备出问题，咱们先做不冒险的排查。",
    "辛苦您反馈这个现象，我先帮您判断轻重，再给对应处理。",
]

EMPATHY_POLICY = [
    "我理解您觉得流程繁琐，但这些环节核心是替您把安全关住。",
    "您问得非常关键，实名和核验不是为难您，是为了避免高风险用气。",
    "辛苦您配合，我把政策背后的安全原因说清楚，您就好判断了。",
]

EMPATHY_CARE = [
    "阿姨您别急，我会用最简单的步骤说，您照着做就行。",
    "您一个人处理确实不容易，我陪您慢慢来，不会让您乱。",
    "辛苦您了，这种情况我按老人友好的方式给您一步一步讲。",
]

INSTR_PREFIX_COMMON = [
    "师傅，",
    "麻烦您，",
    "帮我一下，",
    "我这边情况急，",
    "我先说下情况，",
    "我有点慌，",
    "我普通话一般，",
    "我年纪大记性差，",
]

INSTR_SUFFIX_COMMON = [
    "，麻烦说得直白点。",
    "，你按一二三告诉我。",
    "，我照着做。",
    "，给我个稳妥方案。",
    "，别让我再踩坑了。",
    "，辛苦你了。",
    "，现在就要处理。",
]

INSTR_SUFFIX_SAFETY = [
    "，我真怕出事。",
    "，家里还有老人小孩。",
    "，要不要先撤人？",
    "，咋办才安全？",
]

INSTR_SUFFIX_ORDER = [
    "，我这边等着做饭。",
    "，能给个准确时间吗？",
    "，别让我一直干等。",
    "，我就想知道下一步。",
]

INSTR_SUFFIX_PRICE = [
    "，这笔钱我得弄明白。",
    "，请你把依据讲清楚。",
    "，我不想糊里糊涂付费。",
]

INSTR_SUFFIX_TECH = [
    "，我怕越弄越危险。",
    "，能说下是什么原理吗？",
    "，我先排查哪一步？",
]

INSTR_SUFFIX_POLICY = [
    "，这流程我有点不理解。",
    "，你从安全角度讲给我听。",
    "，我想知道为什么必须这样。",
]

INSTR_SUFFIX_CARE = [
    "，我记不住太复杂的。",
    "，你慢一点说我能跟上。",
    "，我想给家里老人照着念。",
]


@dataclass
class Record:
    category: str
    instruction: str
    input: str
    output: str

    def to_json(self) -> str:
        payload = {
            "instruction": self.instruction,
            "input": self.input,
            "output": self.output,
        }
        return json.dumps(payload, ensure_ascii=False)


def pick(rng: random.Random, items: list[str]) -> str:
    return rng.choice(items)


def decorate_instruction(rng: random.Random, base: str, category: str) -> str:
    prefix = pick(rng, INSTR_PREFIX_COMMON) if rng.random() < 0.7 else ""
    suffix_pool = list(INSTR_SUFFIX_COMMON)
    if category == "safety":
        suffix_pool.extend(INSTR_SUFFIX_SAFETY)
    elif category == "order":
        suffix_pool.extend(INSTR_SUFFIX_ORDER)
    elif category == "price":
        suffix_pool.extend(INSTR_SUFFIX_PRICE)
    elif category == "tech":
        suffix_pool.extend(INSTR_SUFFIX_TECH)
    elif category == "policy":
        suffix_pool.extend(INSTR_SUFFIX_POLICY)
    elif category == "care":
        suffix_pool.extend(INSTR_SUFFIX_CARE)
    suffix = pick(rng, suffix_pool) if rng.random() < 0.8 else ""
    text = f"{prefix}{base}{suffix}".strip()
    if not text.endswith(("？", "。", "！")):
        text += "？"
    return text


def join_steps(steps: list[str]) -> str:
    return "".join(f"{idx + 1}）{step}" for idx, step in enumerate(steps))


def make_output(
    empathy: str,
    steps: list[str],
    tail: str,
    red_line: str,
) -> str:
    return f"{empathy}{join_steps(steps)}{tail}\n【安全红线】{red_line}"


def gen_safety(rng: random.Random) -> Record:
    subtype = rng.choices(
        ["leak", "fire", "illegal_fill", "private_mod", "expired"],
        weights=[30, 22, 18, 15, 15],
        k=1,
    )[0]
    call = pick(rng, ["师傅", "客服", "麻烦你", "师傅我问下", "帮我看下"])
    place = pick(rng, ["家里厨房", "出租屋灶台边", "店里后厨", "老房子阳台", "仓库门口"])
    tone = pick(rng, ["我有点慌", "心里发毛", "我现在手都抖", "我脑子有点乱", "我真怕出事"])

    if subtype == "leak":
        instruction = pick(
            rng,
            [
                f"{call}，{place}一股煤气味，灶没开，{tone}，我先咋整？",
                f"{place}闻到刺鼻味道，家里还有老人孩子，{tone}，要不要先开风扇？",
                f"我半夜闻到液化气味，怀疑软管漏了，{tone}，第一步该做啥？",
                f"屋里闻着像漏气，我普通话不好，您直接说先关哪个阀？",
                f"{place}有味道但找不到漏点，{tone}，能不能点火试一下？",
            ],
        )
        output = make_output(
            pick(rng, EMPATHY),
            [
                "先让家里人撤到室外上风处，保持通道畅通。",
                "立刻关闭钢瓶角阀，停止一切用气操作。",
                "只开门窗自然通风，不要开排风扇和任何电器开关。",
                "到室外再拨打119和燃气服务电话，等待持证人员检测减压阀与软管。",
            ],
            "辛苦您先不要回屋找漏点，专业人员会用检漏液处理。",
            "疑似漏气现场严禁点火、按电器开关、启动车辆或在室内拨打电话。",
        )
    elif subtype == "fire":
        instruction = pick(
            rng,
            [
                f"{call}，钢瓶旁边冒火苗了，我能先泼水不？",
                f"后厨瓶阀附近着火了，员工都慌了，{tone}，先做哪一步？",
                f"减压阀位置窜火，火不大但一直有，我现在该关角阀还是先灭火？",
                f"瓶口有火舌，我担心爆，楼上还有人，咋办最快？",
                f"液化气瓶边上起火了，能不能拿湿毛巾捂住？",
            ],
        )
        output = make_output(
            pick(rng, EMPATHY),
            [
                "先高声示警并组织人员撤离到安全距离外。",
                "在确保可接近的前提下，优先关闭角阀切断气源。",
                "使用干粉灭火器对准火焰根部喷射，保持上风向。",
                "若瓶阀无法关闭或火势扩大，立即撤离并由消防处置。",
            ],
            "您现在最重要的是先保人，不要恋战取物。",
            "钢瓶着火时严禁泼水冲阀门、严禁围观拍摄、严禁无防护近距离处置。",
        )
    elif subtype == "illegal_fill":
        instruction = pick(
            rng,
            [
                f"有人上门说便宜给我灌气，不看证件，靠谱不？",
                f"路边流动充装车说马上灌满还便宜，我能图省钱充吗？",
                f"这瓶子没有追溯码也没封签，对方说都一样，是真的吗？",
                f"邻居推荐黑充装点，说‘一直这么用’，我该不该去？",
                f"商贩说超期瓶也能灌，问题不大，这话能信吗？",
            ],
        )
        output = make_output(
            pick(rng, EMPATHY),
            [
                "先核对充装单位资质和钢瓶追溯码，信息不全直接拒绝。",
                "检查检验标识与下次检验日期，超期瓶必须停用。",
                "查看封签、瓶阀和减压阀外观，异常喷涂或打磨钢印一律不上气。",
                "仅在持证正规站点充装，并保留票据便于追责。",
            ],
            "辛苦您守住这一步，能有效避免来源不明气体风险。",
            "非正规充装、超期钢瓶、来历不明钢瓶一律禁止使用和运输。",
        )
    elif subtype == "private_mod":
        instruction = pick(
            rng,
            [
                f"我想自己拆一下减压阀换新的，网上视频看着不难，能自己搞吗？",
                f"店里忙不过来，我打算临时改下软管和三通，快不快？",
                f"角阀有点涩，我用扳手硬拧一下行不行？",
                f"我朋友说瓶阀漏气自己缠胶带就能顶住，靠谱吗？",
                f"我能不能自己放点残液出来，听说这样火更稳？",
            ],
        )
        output = make_output(
            pick(rng, EMPATHY),
            [
                "先停止用气并关闭角阀，保持现场通风。",
                "不要自行拆卸减压阀、瓶阀和连接软管，防止密封失效。",
                "联系持证维修人员到场检测并更换合规配件。",
                "维修完成后做气密性复检，再恢复供气。",
            ],
            "我知道您是想快点恢复使用，但安全检修必须走专业流程。",
            "严禁私拆阀门、私改管线、私放残液和使用非标配件。",
        )
    else:
        instruction = pick(
            rng,
            [
                f"钢瓶很旧了还生锈，对方说照样能灌，我不太放心，您给句准话。",
                f"我家这瓶检验标识都看不清了，还能继续用吗？",
                f"瓶身凹了点，配送员说问题不大，我该不该拒收？",
                f"超期钢瓶临时用一天行不行？今天做饭急用。",
                f"检验日期过了一个月，充装站不给充，我觉得太死板，这正常吗？",
            ],
        )
        output = make_output(
            pick(rng, EMPATHY),
            [
                "先核对钢瓶检验标识和外观完整性，重点看锈蚀、凹陷和瓶阀状态。",
                "凡是超期或标识不清的钢瓶，立即停用并申请回收置换。",
                "签收前拍照留档，要求配送方提供追溯码和合规凭据。",
                "在新瓶到位前不要冒险续用旧瓶。",
            ],
            "辛苦您坚持按标准执行，短期麻烦能换来长期安全。",
            "超期瓶、重度锈蚀瓶、标识缺失瓶严禁充装和继续使用。",
        )

    instruction = decorate_instruction(rng, instruction, "safety")
    return Record("safety", instruction, "", output)


def gen_order(rng: random.Random) -> Record:
    subtype = rng.choices(
        ["urge", "change_addr", "timeslot", "attitude", "delivery_problem"],
        weights=[30, 20, 20, 15, 15],
        k=1,
    )[0]
    if subtype == "urge":
        instruction = pick(
            rng,
            [
                "我这单等了很久还没到，锅都架上了，能不能马上催一下？",
                "师傅我快断气了，订单一直显示配送中，你帮我盯一下行吗？",
                "今天店里客人多，气还没送到，我真急坏了，多久能到？",
                "我老人孩子都等着做饭，麻烦给个准确到达时间行不行？",
                "都催两次了还没消息，能不能别让我一直干等？",
            ],
        )
        output = make_output(
            pick(rng, EMPATHY_ORDER),
            [
                "先提供订单号或手机号，我立即发起加急催派工单。",
                "我会同步核对配送地址和联系电话，避免骑手空跑。",
                "通常15分钟内回呼最新进度，2小时内给出明确到达时段。",
                "收货时请先核验钢瓶检验标识和减压阀外观，再完成签收。",
            ],
            "让您久等确实辛苦，这单我会持续跟进到送达。",
            "未签收前严禁自行借用来源不明钢瓶或私自倒残液顶用。",
        )
    elif subtype == "change_addr":
        instruction = pick(
            rng,
            [
                "我下单后临时要改地址，骑手还没到，能改到隔壁小区吗？",
                "师傅我填错楼栋了，现在改会不会影响送达时间？",
                "订单已经出发了，我人不在原地址，能不能改去店里？",
                "麻烦帮我把送货点从家里改到门店，今天急用。",
                "刚下单就搬到新房了，地址能立刻改吗？",
            ],
        )
        output = make_output(
            pick(rng, EMPATHY_ORDER),
            [
                "只要骑手未签收完成，原则上可发起一次改地址申请。",
                "我先帮您校验新地址是否在服务范围内，再回传可送达时段。",
                "改址后系统会重新计算路线，通常会顺延30-90分钟。",
                "到货时请确认角阀关闭、软管完好后再连接减压阀。",
            ],
            "辛苦您提前告知，能减少二次派送耽误。",
            "地址不在服务区或现场安全条件不达标时，严禁强行交付钢瓶。",
        )
    elif subtype == "timeslot":
        instruction = pick(
            rng,
            [
                "我白天不在家，能约晚上8点后送吗？",
                "能不能帮我约个固定时段，每周三下午送？",
                "店里中午最忙，别那个点来，能约10点前吗？",
                "我只有午休在家，配送时间能不能精确一点？",
                "请问能提前预约明早第一单吗？",
            ],
        )
        output = make_output(
            pick(rng, EMPATHY_ORDER),
            [
                "您可以提交预约时段，我先帮您锁定可用配送窗口。",
                "系统会按区域运力确认，确认后短信和电话双通知。",
                "若临时变更请至少提前2小时告知，便于改派。",
                "配送到场后先检查瓶阀、减压阀和检验标识，再交接。",
            ],
            "您把可接收时间说清楚，我们就能把等待成本降到最低。",
            "无人签收或通风条件不达标时，严禁将钢瓶留置楼道或门外。",
        )
    elif subtype == "attitude":
        instruction = pick(
            rng,
            [
                "配送员态度很冲，还催我快点签字，这个怎么投诉？",
                "师傅上门说话不耐烦，我心里很不舒服，能处理吗？",
                "我问了两句安全问题，配送员不解释就走，这合理吗？",
                "送气员态度差还不让看钢瓶信息，我要正式反馈。",
                "今天服务体验很差，我想要明确处理结果，不是敷衍道歉。",
            ],
        )
        output = make_output(
            pick(rng, EMPATHY_ORDER),
            [
                "我先为这次体验向您致歉，并立即登记服务态度工单。",
                "请您提供时间、地点和订单号，我们会调取配送记录核查。",
                "一般24小时内给处理结论，涉及培训或处罚会同步结果。",
                "后续配送我可备注“优先解释检验标识和减压阀核验”。",
            ],
            "谢谢您认真反馈，这能帮助我们把服务和安全都做扎实。",
            "配送人员不得跳过安全交底，用户未确认关阀环境前严禁催促接气。",
        )
    else:
        instruction = pick(
            rng,
            [
                "送来的钢瓶和我下单规格不一致，今天还要用，咋处理最快？",
                "到货发现封签破了，我该签收还是退回？",
                "配送到了但瓶身磕碰挺明显，我能拒收吗？",
                "我下单两瓶只到一瓶，另一瓶什么时候补送？",
                "钢瓶追溯码扫不出来，师傅说没事，我该怎么办？",
            ],
        )
        output = make_output(
            pick(rng, EMPATHY_ORDER),
            [
                "先不要签收异常钢瓶，我马上帮您登记异常交付工单。",
                "请拍下钢瓶外观、封签和追溯码，便于我们快速判责。",
                "经核实后会优先安排合规钢瓶补送，并同步预计时间。",
                "签收前务必复核检验标识、瓶阀和减压阀状态。",
            ],
            "您把关得很到位，辛苦您多一步核验。",
            "封签破损、信息不明、规格不符的钢瓶严禁带压使用。",
        )

    instruction = decorate_instruction(rng, instruction, "order")
    return Record("order", instruction, "", output)


def gen_price(rng: random.Random) -> Record:
    subtype = rng.choices(
        ["price_up", "deposit_refund", "floor_fee", "billing", "coupon"],
        weights=[28, 28, 20, 14, 10],
        k=1,
    )[0]
    if subtype == "price_up":
        instruction = pick(
            rng,
            [
                "这月气价怎么又涨了？是不是你们随便加价？",
                "同一小区价格不一样，我觉得不公平，给我解释清楚。",
                "上个月和这月差不少，你们有没有公开价目？",
                "气价涨得太快了，我怀疑被多收了。",
                "为什么节假日前后总涨价，能不能给个依据？",
            ],
        )
        output = make_output(
            pick(rng, EMPATHY_PRICE),
            [
                "我先帮您核对订单单价、钢瓶规格和配送时间段。",
                "液化气价格会受进货成本、运输和区域配送成本影响，我们按公示规则执行。",
                "如您怀疑多收，我可发起账单复核，通常24小时内反馈结果。",
                "后续可选择价格提醒服务，价格波动前先通知您。",
            ],
            "您提得合理，费用问题我们必须做到可追溯、可解释。",
            "任何未公示费用都不得收取，且不得以低价来源不明钢瓶替代合规供气。",
        )
    elif subtype == "deposit_refund":
        instruction = pick(
            rng,
            [
                "我都退瓶一周了，押金怎么还没到账？",
                "押金退得太慢了，我跑了两趟还没办完，咋回事？",
                "退押金要这么多材料吗？感觉故意卡我。",
                "钢瓶回收了，押金一直显示处理中，什么时候能打款？",
                "我老爸不会手机操作，押金能线下办快点吗？",
            ],
        )
        output = make_output(
            pick(rng, EMPATHY_PRICE),
            [
                "辛苦您跑一趟，我先核验退瓶登记、押金凭证和收款账户。",
                "资料齐全情况下通常3-7个工作日到账，节假日顺延。",
                "若超时未到账，我可立即升级为加急退款工单并跟踪到入账。",
                "退押同时会核查钢瓶检验标识与回收状态，避免账务错配。",
            ],
            "您的时间我们重视，我会把节点写清楚发给您。",
            "未完成回收核验的钢瓶不得重复流转或私下交易押金。",
        )
    elif subtype == "floor_fee":
        instruction = pick(
            rng,
            [
                "我住二楼也收楼层费，这合理吗？",
                "楼层费怎么算的？每次都不一样我不接受。",
                "电梯房还收上楼费，规则到底是什么？",
                "我自己下楼拿瓶还要楼层费吗？",
                "楼层费没有提前说清楚，我想申诉。",
            ],
        )
        output = make_output(
            pick(rng, EMPATHY_PRICE),
            [
                "楼层费按公示标准与是否电梯、人工搬运距离综合计算。",
                "我先调取该单计费明细，给您逐项核对收费依据。",
                "若存在误收，我们会原路退回并修正后续计费。",
                "您也可选择楼下指定交接点，减少搬运附加费用。",
            ],
            "这项费用必须透明，您有异议我们就按流程复核到位。",
            "不得在未告知收费规则的情况下强行收费或以不合规钢瓶替代服务。",
        )
    elif subtype == "billing":
        instruction = pick(
            rng,
            [
                "这单金额和下单时不一样，能不能给我明细？",
                "发票金额对不上，我要重新核对账单。",
                "为什么多了个服务费？我下单页没看到。",
                "你们账单里写‘其他费用’，这是什么？",
                "我想把近三个月账单都导出来核对。",
            ],
        )
        output = make_output(
            pick(rng, EMPATHY_PRICE),
            [
                "我先给您出具本单费用拆分：气费、配送费、可选服务费。",
                "与下单页不一致的项目会重点核查，确认异常立即更正。",
                "发票可按实付金额重开，处理时效一般1-3个工作日。",
                "若涉及钢瓶置换，会同步核验检验标识和回收记录。",
            ],
            "您认真核账非常必要，我们支持全流程留痕查询。",
            "账单异常未核清前，严禁以口头承诺代替正式费用确认。",
        )
    else:
        instruction = pick(
            rng,
            [
                "券明明没过期，下单却不能用，是不是系统故意限制？",
                "活动价和结算价不一致，我感觉被套路了。",
                "新客优惠怎么突然失效了？给个说法。",
                "我用了优惠券还比上次贵，哪里算错了？",
                "门店说线上券不能用，规则到底听谁的？",
            ],
        )
        output = make_output(
            pick(rng, EMPATHY_PRICE),
            [
                "我先核对优惠券适用范围、有效期和钢瓶规格限制。",
                "活动与基础气价叠加规则会在结算页展示，我给您逐项解释。",
                "若系统判定异常，我可发起人工复核并补偿差额。",
                "后续下单前可先做试算，避免临门结算落差。",
            ],
            "您的疑问很正常，我们会把规则说清，不让您吃信息差。",
            "任何优惠活动都不能突破安全配送与合规充装底线。",
        )

    instruction = decorate_instruction(rng, instruction, "price")
    return Record("price", instruction, "", output)


def gen_tech(rng: random.Random) -> Record:
    subtype = rng.choices(
        ["yellow_flame", "winter_pressure", "no_ignite", "rust", "unstable_flame"],
        weights=[28, 22, 20, 12, 18],
        k=1,
    )[0]
    if subtype == "yellow_flame":
        instruction = pick(
            rng,
            [
                "我家火苗发黄还冒黑烟，是不是气有问题？",
                "锅底老熏黑，怎么调都不对，您给我讲讲原理。",
                "最近做饭火发红发黄，闻着也怪怪的，咋处理？",
                "灶火不蓝了，炒菜时间变长，是减压阀坏了吗？",
                "黄火很明显，我怕一氧化碳，先做啥最稳妥？",
            ],
        )
        output = make_output(
            pick(rng, EMPATHY_TECH),
            [
                "黄火多数是一次空气不足，先暂停使用并保持通风。",
                "检查灶具风门、喷嘴和减压阀匹配是否正常。",
                "清理油污积碳后试火，正常应以稳定蓝火为主。",
                "若仍有黑烟或异味，安排上门检测软管与燃烧工况。",
            ],
            "原理上说，空气混合不足会降低燃烧效率并产生积碳。",
            "持续黄火、回火或异味时必须停用，严禁强行继续烹饪。",
        )
    elif subtype == "winter_pressure":
        instruction = pick(
            rng,
            [
                "冬天火老是小，烧半天不开，气是不是掺假了？",
                "天气一冷就没劲，是不是钢瓶快坏了？",
                "同一瓶气夏天好用冬天不给力，啥原因？",
                "最近火忽大忽小，听说跟气化速度有关，真是这样吗？",
                "寒天里做饭慢得很，怎么判断是瓶里气少还是压力低？",
            ],
        )
        output = make_output(
            pick(rng, EMPATHY_TECH),
            [
                "冬季温度低会让液化气气化速度下降，火力波动是常见现象。",
                "先确认钢瓶余量，再检查减压阀是否老化或结霜异常。",
                "保持厨房通风并避免钢瓶受潮受冻，必要时更换合规减压阀。",
                "若持续不稳，请预约工单做压力与燃烧联合检测。",
            ],
            "不是推责任，低温工况确实会影响出气稳定性。",
            "严禁明火加热钢瓶或烘烤减压阀来“提压”。",
        )
    elif subtype == "no_ignite":
        instruction = pick(
            rng,
            [
                "灶具突然打不着火，电池刚换过，下一步怎么查？",
                "点火只听见哒哒声不着，急着做饭咋办？",
                "一边灶能点着另一边不行，是不是喷嘴堵了？",
                "新换钢瓶后打火困难，我怕接错了。",
                "老人家说怎么也点不着，我远程该怎么教他？",
            ],
        )
        output = make_output(
            pick(rng, EMPATHY_TECH),
            [
                "先确认角阀已开启且钢瓶有余量，再检查电池正负极。",
                "观察是否有出气声，若无出气重点排查减压阀与软管折扁。",
                "有出气但不点火时，清理点火针与喷嘴积污。",
                "反复失败请停用并报修，由持证人员做气密和点火系统检测。",
            ],
            "您先别反复点，连续打火会增加风险。",
            "疑似漏气或点火异常时严禁反复试火、严禁自行拆改点火系统。",
        )
    elif subtype == "rust":
        instruction = pick(
            rng,
            [
                "钢瓶表面有锈斑还能继续用吗？",
                "瓶底有点鼓包和掉漆，我心里不踏实，能换吗？",
                "配送来的瓶子有锈，我是不是该直接拒收？",
                "老瓶子放阳台淋雨后生锈了，会不会有危险？",
                "瓶身锈得厉害但还能出气，这种要马上停吗？",
            ],
        )
        output = make_output(
            pick(rng, EMPATHY_TECH),
            [
                "轻微表面锈可先拍照留档，重点看是否伴随鼓包、裂纹和瓶阀异常。",
                "若锈蚀较重或检验标识不清，建议立即停用并申请置换。",
                "签收或复用前核验检验标识和追溯码，确认在检验周期内。",
                "置换期间保持角阀关闭，避免频繁搬动碰撞。",
            ],
            "您谨慎是对的，钢瓶状态直接关系到长期用气安全。",
            "重度锈蚀、变形或标识缺失钢瓶严禁继续充装和使用。",
        )
    else:
        instruction = pick(
            rng,
            [
                "火一会大一会小，还偶尔‘噗’一下，是哪儿有毛病？",
                "炒菜时火忽明忽暗，我怕回火，怎么排查？",
                "灶具时不时回火，声音吓人，能先凑合用吗？",
                "同样开度，今天火比昨天小很多，是减压阀不稳吗？",
                "用着用着火突然变弱，过会儿又正常，这情况常见吗？",
            ],
        )
        output = make_output(
            pick(rng, EMPATHY_TECH),
            [
                "火力忽大忽小常见于减压阀老化、软管受压或喷嘴堵塞。",
                "先关角阀停用，检查软管是否折扁、接口是否松动。",
                "清洁灶头后小火复测，观察是否仍有回火或异响。",
                "若问题反复，安排上门更换减压阀并做气密性检测。",
            ],
            "您担心得对，这类波动问题不能长期拖着用。",
            "出现回火、异响、异味时必须立即停用，严禁继续带故障运行。",
        )

    instruction = decorate_instruction(rng, instruction, "tech")
    return Record("tech", instruction, "", output)


def gen_policy(rng: random.Random) -> Record:
    subtype = rng.choice(["realname", "inspection", "expired_refuse", "recording"])
    if subtype == "realname":
        instruction = pick(
            rng,
            [
                "为什么订个气还要实名，我就买瓶气这么麻烦吗？",
                "我不想留身份证信息，不实名就不能下单吗？",
                "老人不会实名，能不能直接现金买气？",
                "实名是不是泄露隐私？我有点顾虑。",
                "同城别家不要实名，你们为什么这么严？",
            ],
        )
        output = make_output(
            pick(rng, EMPATHY_POLICY),
            [
                "实名主要用于钢瓶流向追溯和事故快速联络，不是额外门槛。",
                "我们仅采集必要信息并按隐私规则存储，避免信息滥用。",
                "若是老人不会操作，可走人工辅助实名通道。",
                "实名完成后，后续下单会更快并减少核验次数。",
            ],
            "咱们把信息管好，是为了关键时刻能第一时间保护到您。",
            "拒绝实名将无法完成合规供气，严禁线下绕过系统私下供气。",
        )
    elif subtype == "inspection":
        instruction = pick(
            rng,
            [
                "上门安全检查必须做吗？我家很忙不想被打扰。",
                "你们老说要看灶具和减压阀，这是强制的吗？",
                "为什么送气前还要看通风，太耽误时间了。",
                "检查一次不够吗，怎么还要复检？",
                "我家一直正常，用了好多年还查什么？",
            ],
        )
        output = make_output(
            pick(rng, EMPATHY_POLICY),
            [
                "上门检查主要看角阀、减压阀、软管和通风，不是形式流程。",
                "很多风险在外观早期就能发现，复检是防止老化后突发故障。",
                "检查合格后会缩短后续配送沟通成本，减少临时停气概率。",
                "您可预约时间段，我们尽量不影响作息。",
            ],
            "辛苦您配合一次检查，等于给家里加了一道长期保险。",
            "检查不合格前严禁强行通气或继续带隐患使用。",
        )
    elif subtype == "expired_refuse":
        instruction = pick(
            rng,
            [
                "我的瓶子就超期一点点，为什么坚决不给充？",
                "超期瓶外观看着没事，不能通融一次吗？",
                "充装站拒充我很不理解，这不是小题大做吗？",
                "我今天急用，超期瓶先充一回行不行？",
                "过检日期才几天，非得换瓶吗？",
            ],
        )
        output = make_output(
            pick(rng, EMPATHY_POLICY),
            [
                "超期后钢瓶强度和密封可靠性无法保证，必须先复检。",
                "拒充不是针对个人，而是统一执行安全底线。",
                "我可帮您走置换流程，优先安排合规钢瓶配送。",
                "新瓶到位后再接减压阀，避免临时冒险用气。",
            ],
            "我理解您急用，但这条线不能放松，咱们先把风险关住。",
            "超期钢瓶未复检前严禁充装、运输和继续使用。",
        )
    else:
        instruction = pick(
            rng,
            [
                "客服通话为什么要录音？是不是不信任我们？",
                "你们留配送记录干嘛，我担心被乱用。",
                "投诉还要我提供时间和地址，是不是故意拖？",
                "每次都要核对手机号，流程太繁琐了。",
                "订单记录能删吗？我不想留太多信息。",
            ],
        )
        output = make_output(
            pick(rng, EMPATHY_POLICY),
            [
                "录音和记录用于服务追溯与纠纷保护，关键时刻可还原事实。",
                "我们按最小必要原则保存信息，仅用于配送和安全联络。",
                "核对手机号是防止错送和冒领，能减少钢瓶流转风险。",
                "如需查询或更正信息，可走隐私工单通道处理。",
            ],
            "您对隐私的重视是对的，我们也按规则把边界守住。",
            "任何信息核验未完成的订单不得进行钢瓶交付。",
        )

    instruction = decorate_instruction(rng, instruction, "policy")
    return Record("policy", instruction, "", output)


def gen_care(rng: random.Random) -> Record:
    subtype = rng.choices(
        ["elderly", "restaurant_busy", "new_home", "remote_help"],
        weights=[35, 30, 20, 15],
        k=1,
    )[0]
    if subtype == "elderly":
        instruction = pick(
            rng,
            [
                "我一个老太太不会弄这个阀门，你慢点教我行不行？",
                "我爸一个人住，闻到气味就慌，能给个最简单步骤吗？",
                "老人手劲小，角阀拧不动怎么办？",
                "阿姨我年纪大记不住，你能按一二三说吗？",
                "家里老人独居，换瓶后总怕漏气，怎么教他更安心？",
            ],
        )
        output = make_output(
            pick(rng, EMPATHY_CARE),
            [
                "第一步先关角阀，第二步开门窗，第三步离开厨房到安全处。",
                "如果阀门太紧，不要硬拧，直接联系持证人员上门。",
                "建议把应急电话贴在灶台旁，方便老人一键联系。",
                "后续可申请老人关怀回访，定期检查减压阀和软管。",
            ],
            "您做得已经很好了，慢一点没关系，安全第一。",
            "老人独居场景下严禁自行拆阀、严禁在异味环境中反复试火。",
        )
    elif subtype == "restaurant_busy":
        instruction = pick(
            rng,
            [
                "午市最忙的时候突然断气，后厨全乱了，能不能紧急处理？",
                "店里高峰期气压掉得快，顾客都在等，怎么稳住？",
                "餐馆突然没火，员工急着上菜，我该先做啥？",
                "后厨两口锅都要用，今天火力不足，能加急换瓶吗？",
                "忙时断气最怕客诉，帮我出个不出事故的处理顺序。",
            ],
        )
        output = make_output(
            pick(rng, EMPATHY_CARE),
            [
                "先暂停明火作业并关闭角阀，安排员工分区疏导顾客。",
                "我这边可优先发起商户加急工单，并回传预计到达时段。",
                "等待期间检查减压阀、软管和备用瓶检验标识是否合规。",
                "恢复供气后先小火试运行，再逐步恢复高峰出餐。",
            ],
            "辛苦您在高压时段先稳住现场，先保安全再保出餐效率。",
            "商户高峰期严禁并联私接钢瓶、严禁私放残液应急。",
        )
    elif subtype == "new_home":
        instruction = pick(
            rng,
            [
                "我刚搬新房，开户和首瓶怎么安排才不踩坑？",
                "新家第一次用液化气，怕操作错，能给保姆级流程吗？",
                "装修完准备开火做饭，开户要准备哪些证件？",
                "新房厨房通风一般，能先送瓶后补检查吗？",
                "第一次办气卡我有点懵，麻烦你按步骤说清楚。",
            ],
        )
        output = make_output(
            pick(rng, EMPATHY_CARE),
            [
                "先准备身份信息和用气地址，提交开户申请。",
                "上门前会核验厨房通风、角阀位置、减压阀和软管配置。",
                "核验通过后再安排首瓶配送并做点火安全交底。",
                "建议首次使用时家里留一位成年人全程在场。",
            ],
            "新房第一次用气慢一点最稳妥，我会把关键点都给您标出来。",
            "未完成安全核验前严禁先接气、先点火或私自改装灶具。",
        )
    else:
        instruction = pick(
            rng,
            [
                "我在外地，家里老人说闻到味道，我电话里怎么指导最安全？",
                "我妈不会看检验标识，你教我怎么远程让她核对。",
                "家里只剩老人和孩子，我不在现场，遇到漏气该怎么远程指挥？",
                "我爸听力不好，电话指导怕听错，有没有简单口诀？",
                "我想给家里做个应急卡片，你帮我总结最关键三步。",
            ],
        )
        output = make_output(
            pick(rng, EMPATHY_CARE),
            [
                "先让家人复述三步：关角阀、开门窗、撤到室外。",
                "要求老人不要碰电器开关，不要在室内打电话。",
                "让邻居协助现场照看，同时联系119和燃气服务。",
                "事后安排上门复检减压阀、软管与瓶阀密封状态。",
            ],
            "您远程处理已经很负责了，重点是让家人按固定口令执行。",
            "远程指导场景下严禁让老人独自排障或回屋点火试漏。",
        )

    instruction = decorate_instruction(rng, instruction, "care")
    return Record("care", instruction, "", output)


GENERATOR_MAP: dict[str, Callable[[random.Random], Record]] = {
    "safety": gen_safety,
    "order": gen_order,
    "price": gen_price,
    "tech": gen_tech,
    "policy": gen_policy,
    "care": gen_care,
}

TARGET_PER_BATCH = {
    "safety": 25,
    "order": 22,
    "price": 16,
    "tech": 23,
    "policy": 6,
    "care": 8,
}

CANDIDATE_PER_BATCH_BY_CAT = {
    "safety": 30,
    "order": 26,
    "price": 20,
    "tech": 27,
    "policy": 7,
    "care": 10,
}


def normalize_text(text: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", text.lower())


def contains_term(text: str) -> bool:
    return any(term in text for term in TERMS)


def starts_with_empathy(text: str) -> bool:
    markers = ["理解", "辛苦", "别慌", "先别急", "我会", "我先"]
    return any(marker in text[:24] for marker in markers)


def valid_record(record: Record) -> bool:
    if not record.instruction or not record.output:
        return False
    if record.input != "":
        return False
    if "【安全红线】" not in record.output:
        return False
    if not contains_term(record.output):
        return False
    if not starts_with_empathy(record.output):
        return False
    return True


def too_similar(text: str, accepted: list[str], threshold: float = 0.88) -> bool:
    for prev in accepted:
        if SequenceMatcher(None, text, prev).ratio() >= threshold:
            return True
    return False


def high_similarity_rate(records: list[Record], threshold: float = 0.86) -> float:
    n = len(records)
    if n < 2:
        return 0.0
    similar_pairs = 0
    total_pairs = n * (n - 1) // 2
    instr = [normalize_text(r.instruction) for r in records]
    for i in range(n):
        for j in range(i + 1, n):
            if SequenceMatcher(None, instr[i], instr[j]).ratio() >= threshold:
                similar_pairs += 1
    return (similar_pairs / total_pairs) * 100.0


def generate_candidates(rng: random.Random) -> list[Record]:
    candidates: list[Record] = []
    for cat, count in CANDIDATE_PER_BATCH_BY_CAT.items():
        gen = GENERATOR_MAP[cat]
        while len([x for x in candidates if x.category == cat]) < count:
            rec = gen(rng)
            if valid_record(rec):
                candidates.append(rec)
    rng.shuffle(candidates)
    return candidates


def select_batch(
    rng: random.Random,
    global_norm_instr: set[str],
    global_instr_samples: list[str],
) -> list[Record]:
    max_attempts = 180
    for _ in range(max_attempts):
        selected: list[Record] = []
        cat_count = {k: 0 for k in TARGET_PER_BATCH}
        local_norm_set = set(global_norm_instr)
        rounds = 0

        while len(selected) < BATCH_SIZE and rounds < 24:
            rounds += 1
            candidates = generate_candidates(rng)
            for rec in candidates:
                cat = rec.category
                if cat_count[cat] >= TARGET_PER_BATCH[cat]:
                    continue
                norm = normalize_text(rec.instruction)
                if norm in local_norm_set:
                    continue
                if not valid_record(rec):
                    continue
                selected.append(rec)
                cat_count[cat] += 1
                local_norm_set.add(norm)
                if len(selected) == BATCH_SIZE:
                    break

        if len(selected) != BATCH_SIZE:
            continue
        if high_similarity_rate(selected) > 8.0:
            continue

        for rec in selected:
            norm = normalize_text(rec.instruction)
            global_norm_instr.add(norm)
            global_instr_samples.append(norm)
        return selected

    raise RuntimeError("Batch selection failed after retries")


def write_jsonl(path: Path, records: list[Record]) -> None:
    lines = [r.to_json() for r in records]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def validate_file(path: Path) -> dict[str, int | float]:
    lines = path.read_text(encoding="utf-8").splitlines()
    parsed = []
    fields_ok = 0
    redline_ok = 0
    term_ok = 0
    empathy_ok = 0
    for line in lines:
        obj = json.loads(line)
        parsed.append(obj)
        if set(obj.keys()) == {"instruction", "input", "output"}:
            fields_ok += 1
        if "【安全红线】" in obj["output"]:
            redline_ok += 1
        if contains_term(obj["output"]):
            term_ok += 1
        if starts_with_empathy(obj["output"]):
            empathy_ok += 1
    sim_rate = high_similarity_rate(
        [Record("", x["instruction"], x["input"], x["output"]) for x in parsed]
    )
    return {
        "lines": len(lines),
        "json_ok": len(parsed),
        "fields_ok": fields_ok,
        "redline_ok": redline_ok,
        "term_ok": term_ok,
        "empathy_ok": empathy_ok,
        "similarity_rate_percent": round(sim_rate, 4),
    }


def main() -> None:
    rng = random.Random(SEED)
    global_norm_instr: set[str] = set()
    global_instr_samples: list[str] = []
    all_records: list[Record] = []
    report: dict[str, dict[str, int | float]] = {}

    for batch_idx in range(1, BATCH_COUNT + 1):
        records = select_batch(rng, global_norm_instr, global_instr_samples)
        batch_path = OUTPUT_DIR / BATCH_FILE_TMPL.format(batch_idx)
        write_jsonl(batch_path, records)
        report[batch_path.name] = validate_file(batch_path)
        all_records.extend(records)

    merged_path = OUTPUT_DIR / MERGED_FILE
    write_jsonl(merged_path, all_records)
    report[merged_path.name] = validate_file(merged_path)

    report_path = OUTPUT_DIR / "qwen25_7b_lpg_train_data_quality_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # Keep the initial sample file as reference only; do not overwrite it here.


if __name__ == "__main__":
    main()
