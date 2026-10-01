"""Small ten-band U-Net used only by the isolated plume experiment."""

import torch
from torch import nn
from torch.nn import functional as F


class DoubleConv(nn.Sequential):
    def __init__(self, incoming, outgoing):
        super().__init__(
            nn.Conv2d(incoming, outgoing, 3, padding=1, bias=False),
            nn.GroupNorm(8, outgoing),
            nn.ReLU(inplace=True),
            nn.Conv2d(outgoing, outgoing, 3, padding=1, bias=False),
            nn.GroupNorm(8, outgoing),
            nn.ReLU(inplace=True),
        )


class UNet(nn.Module):
    def __init__(self):
        super().__init__()
        self.encoder = nn.ModuleList([
            DoubleConv(10, 16), DoubleConv(16, 32), DoubleConv(32, 64),
            DoubleConv(64, 128), DoubleConv(128, 256),
        ])
        self.decoder = nn.ModuleList([
            DoubleConv(256 + 128, 128), DoubleConv(128 + 64, 64),
            DoubleConv(64 + 32, 32), DoubleConv(32 + 16, 16),
        ])
        self.head = nn.Conv2d(16, 3, 1)

    def forward(self, image):
        skips = []
        x = image
        for block in self.encoder[:-1]:
            x = block(x)
            skips.append(x)
            x = F.max_pool2d(x, 2)
        x = self.encoder[-1](x)
        for block, skip in zip(self.decoder, reversed(skips)):
            x = F.interpolate(x, size=skip.shape[-2:], mode='bilinear', align_corners=False)
            x = block(torch.cat((x, skip), dim=1))
        return self.head(x)
