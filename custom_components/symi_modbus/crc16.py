# -*-coding:utf8-*-

def crc16_fn(datas):
    # 输入数据后，打印一下列表
    crc16=0xFFFF
    poly=0xA001
    for data in datas:
    # 表示将datas列表中的每一个变量赋值给data，
    # 在此你可以自由输入数据，校验的次数是由你输入的数据的多少决定的
        # print(a)
        crc16 = data ^ crc16
        #^ 异或运算：如果两个位为"异"（值不同），则该位结果为1，否则为0。
        for i in range(8):
            # 对于每一个data，都需要右移8次，可以简单理解为对每一位都完成了校验
            if 1&(crc16) == 1:
                # crc16与上1 的结果(16位二进制)只有第0位是1或0，其他位都是0
                # & 与运算：都是1才是1，否则为0
                crc16 = crc16 >> 1
                # >>表示右移，即从高位向低位移出，最高位补0
                crc16 = crc16^poly
            else:
                crc16 = crc16 >> 1
    return [crc16 & 0xff,crc16>>8] 