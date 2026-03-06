export const NAV_LINKS = [
  { path: "/portal/dashboard", label: "工作台" },
  { path: "/portal/order/new", label: "下单服务" },
  { path: "/portal/store", label: "配件商城" },
  { path: "/portal/orders", label: "订单管理" },
  { path: "/portal/chat", label: "在线客服" },
  { path: "/portal/profile", label: "个人中心" }
];

export const SERVICE_CARDS = [
  {
    id: "delivery",
    code: "LPG_CYLINDER_DELIVERY",
    title: "瓶装配送",
    desc: "即时配送，安全送达",
    icon: "🛻"
  },
  { id: "exchange", code: "CYLINDER_EXCHANGE", title: "换瓶", desc: "以旧换新，合规处理", icon: "🔄" },
  { id: "install", code: "INSTALLATION", title: "安装", desc: "专业安装，上门服务", icon: "🔧" },
  { id: "safety", code: "SAFETY_CHECK", title: "安检", desc: "排查隐患，守护安全", icon: "🛡️" },
  { id: "repair", code: "REPAIR", title: "报修", desc: "快速响应，专业修复", icon: "🧰" },
  { id: "accessories", code: "ACCESSORIES", title: "配件", desc: "正品配件，质量保障", icon: "🛒" }
];

export const ORDER_LIST = [
  {
    id: "LPG202310240001",
    title: "瓶装配送(15kg)",
    time: "2023-10-24 10:00",
    eta: "预计 09:00 - 11:00",
    address: "上海市浦东新区莱茵路 123 号 502 室",
    status: "待付款",
    amount: "¥120.00",
    action: "立即付款"
  },
  {
    id: "LPG202310230582",
    title: "报修服务",
    time: "2023-10-23 15:45",
    eta: "2023-10-25 09:00 - 11:00",
    address: "上海市松江区三湘路 99 号",
    status: "已预约",
    amount: "¥99.00",
    action: "修改地址"
  },
  {
    id: "LPG202310200421",
    title: "配件：燃气软管(2米)",
    time: "2023-10-20 08:30",
    eta: "2023-10-20 16:15",
    address: "上海市闵行区星城路 456 号",
    status: "已完成",
    amount: "¥35.00",
    action: "再来一单"
  }
];

export const ACCESSORY_ITEMS = [
  { id: "hose", name: "耐高温耐腐蚀软管", price: "¥35.00", tag: "常备" },
  { id: "regulator", name: "安全减压阀", price: "¥80.00", tag: "热卖" },
  { id: "alarm", name: "智能燃气报警器", price: "¥120.00", tag: "新品" }
];

export const ADDRESSES = [
  {
    id: "addr-1",
    name: "张建国",
    phone: "138 **** 0000",
    tag: "默认",
    address: "北京市朝阳区 紫金街 120 号 3 层"
  },
  {
    id: "addr-2",
    name: "李美华",
    phone: "139 **** 1111",
    tag: "",
    address: "上海市浦东新区 莱茵路 8 号 2 单元 302"
  },
  {
    id: "addr-3",
    name: "王经理",
    phone: "189 **** 0011",
    tag: "企业",
    address: "浙江省杭州市 江干区虹桥 611 号 3 号楼"
  }
];

export const QUICK_QUESTIONS = [
  "下订单",
  "查询订单",
  "查看我的地址",
  "我要联系客服"
];
