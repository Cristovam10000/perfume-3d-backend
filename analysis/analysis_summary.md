# Análise do benchmark

## Taxa de sucesso por método

| Método | ok | total | taxa |
|---|---|---|---|
| IA | 24 | 26 | 92.3% |
| Blander | 24 | 26 | 92.3% |
| Meshroom | 0 | 24 | 0.0% |

## Médias por método — modo matte

| Método | n | Chamfer L1 ↓ | Chamfer L2 ↓ | Hausdorff ↓ | F-Score@1% ↑ | F-Score@5% ↑ |
|---|---|---|---|---|---|---|
| IA | 13 | 0.0370 ± 0.0329 | 0.0021 ± 0.0033 | 0.1065 ± 0.0558 | 0.5637 ± 0.2728 | 0.9087 ± 0.1537 |
| Blander | 13 | 0.1053 ± 0.0398 | 0.0093 ± 0.0059 | 0.1630 ± 0.0458 | 0.1364 ± 0.0966 | 0.5625 ± 0.1919 |

## Médias por método — modo realistic

| Método | n | Chamfer L1 ↓ | Chamfer L2 ↓ | Hausdorff ↓ | F-Score@1% ↑ | F-Score@5% ↑ |
|---|---|---|---|---|---|---|
| IA | 11 | 0.0350 ± 0.0254 | 0.0016 ± 0.0022 | 0.1044 ± 0.0508 | 0.5303 ± 0.2313 | 0.9210 ± 0.1185 |
| Blander | 11 | 0.0971 ± 0.0379 | 0.0082 ± 0.0061 | 0.1663 ± 0.0472 | 0.1492 ± 0.0534 | 0.6192 ± 0.1793 |

## Wilcoxon pareado IA × Blander

| Modo | Métrica | n pares | mediana IA | mediana Blander | p-valor | significativo? |
|---|---|---|---|---|---|---|
| matte | Chamfer L1 ↓ | 13 | 0.0257 | 0.1003 | 0.001221 | sim (p<0,05) |
| matte | F-Score@1% ↑ | 13 | 0.6115 | 0.1036 | 0.0007324 | sim (p<0,05) |
| realistic | Chamfer L1 ↓ | 11 | 0.0242 | 0.0872 | 0.0009766 | sim (p<0,05) |
| realistic | F-Score@1% ↑ | 11 | 0.5840 | 0.1418 | 0.001953 | sim (p<0,05) |
