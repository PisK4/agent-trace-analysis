## Variant: dsh 仪器复用

### Design stance
把 Atatrace 画成一台轮次账本仪器：30px 行、色块事件标签、粗分割线、三车道 Overview。只借 dsh Trajectory 的视觉模式，不借它的产品名。

### Key choices
- Layout: 窄会话轨 + 全高账本 + 选中后右侧检查器
- Typography: 系统无衬线 + 等宽数字；行高按仪器表对齐
- Color: 冷灰底；User 蓝、Assistant 紫、Tool 琥珀
- Interaction: 点行打开检查器；点时间轴条选中对应行；上滚暂停跟随

### Trade-offs
- Strong at: 长账本扫描、Turn 边界、和 dsh 对照验收
- Weak at: 气质接近参考实现，品牌识别弱

### Best for
已经认 dsh 账本、要先确认合同有没有画对的人
