import torch
import torch.nn as nn


def _make_divisible(ch, divisor=8, min_ch=None):
    """
    This function is taken from the original tf repo.
    It ensures that all layers have a channel number that is divisible by 8
    It can be seen here:
    https://github.com/tensorflow/models/blob/master/research/slim/nets/mobilenet/mobilenet.py
    :param ch:
    :param divisor:
    :param min_ch:
    :return:
    """
    if min_ch is None:
        min_ch = divisor
    new_ch = max(min_ch, int(ch + divisor / 2) // divisor * divisor)

    # Make sure that round down does not go down by more than 10%.
    if new_ch < 0.9*ch:
        new_ch += divisor
    return new_ch


class ConvBNReLU(nn.Sequential):
    """
    这里参考官方实现，继承自nn.Sequential
    """
    def __init__(self, in_channel, out_channel, kernel_size=3, stride=1, groups=1):
        # 这里的groups，设置为1的时候，相当于普通卷积，设置为其它数值就相当于DW（DepthWise）卷积。
        padding = (kernel_size - 1) // 2  # padding值根据kernel size设置，当kernel size为1，padding为0。
        super(ConvBNReLU, self).__init__(
            nn.Conv2d(in_channel, out_channel, kernel_size, stride, padding, groups=groups, bias=False),  # 使用BN就不使用偏置
            nn.BatchNorm2d(out_channel),  # bn层输入维度为上一层的输出，也就是out channel
            nn.ReLU6(inplace=True)
        )


class InvertedResidual(nn.Module):
    """
    定义倒残差结构
    """
    def __init__(self, in_channel, out_channel, stride, expand_ratio):  # expand_ratio 扩展因子，论文中的t
        super(InvertedResidual, self).__init__()
        hidden_channel = in_channel * expand_ratio  # hidden_channel
        # self.use_shortcut = (stride == 1 and in_channel == out_channel) 当步长为1且输入输出特征矩阵维度相等时才使用shortcut连接
        self.use_shortcut = stride == 1 and in_channel == out_channel

        layers = []
        if expand_ratio != 1:
            # use 1x1 pointwise conv. 若扩展因子不为1，不执行这一步。
            layers.append(ConvBNReLU(in_channel, hidden_channel, kernel_size=1))
        layers.extend(
            [
                # 3x3 depthwise conv
                ConvBNReLU(in_channel=hidden_channel, out_channel=hidden_channel, stride=stride, groups=hidden_channel),
                # 1x1 pointwise conv
                nn.Conv2d(hidden_channel, out_channel, kernel_size=1, bias=False),
                nn.BatchNorm2d(out_channel)
            ]
        )
        self.conv = nn.Sequential(*layers)

    def forward(self, x):
        if self.use_shortcut:
            return x + self.conv(x)
        else:
            return self.conv(x)


class MobileNetV2(nn.Module):
    def __init__(self, num_classes=1000, alpha=1.0, round_nearest=8):  # alpha控制卷积层所使用卷积核个数的倍率。
        super(MobileNetV2, self).__init__()
        block = InvertedResidual
        input_channel = _make_divisible(32*alpha, round_nearest)
        last_channel = _make_divisible(1280*alpha, round_nearest)

        inverted_residual_setting = [
            # t, c, n, s
            [1, 16, 1, 1],
            [6, 24, 2, 2],
            [6, 32, 3, 2],
            [6, 64, 4, 2],
            [6, 96, 3, 1],
            [6, 160, 3, 2],
            [6, 320, 1, 1],
        ]

        features = []
        # conv1 layer
        features.append(ConvBNReLU(3, input_channel, stride=2))
        # building inverted residual blocks.
        for t, c, n, s in inverted_residual_setting:
            output_channel = _make_divisible(c * alpha, round_nearest)
            for i in range(n):
                stride = s if i == 0 else 1
                features.append(block(input_channel, output_channel, stride, expand_ratio=t))
                input_channel = output_channel
            # building last several layers
        features.append(ConvBNReLU(input_channel, last_channel, 1))
        # combine feature layers
        self.features = nn.Sequential(*features)

        # building classifier
        self.avgpool = nn.AdaptiveAvgPool2d((1, 1))
        self.classifier = nn.Sequential(
            nn.Dropout(0.2),
            nn.Linear(last_channel, num_classes)
        )

        # weight initialization
        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                nn.init.kaiming_normal_(m.weight, mode='fan_out')
                if m.bias is not None:
                    nn.init.zeros_(m.bias)
            elif isinstance(m, nn.BatchNorm2d):
                nn.init.ones_(m.weight)
                nn.init.zeros_(m.bias)
            elif isinstance(m, nn.Linear):
                nn.init.normal_(m.weight, 0, 0.01)
                nn.init.zeros_(m.bias)

    def forward(self, x):
        x = self.features(x)
        x = self.avgpool(x)
        x = torch.flatten(x, 1)
        x = self.classifier(x)

        return x
