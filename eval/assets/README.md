# Assets do módulo eval

## HDRI

### `studio_small_08_1k.hdr` (1.5 MB)

- **Fonte**: [Poly Haven](https://polyhaven.com/a/studio_small_08)
- **Autor**: Sergej Majboroda
- **Licença**: **CC0 1.0** (domínio público — uso comercial e modificação livres, sem atribuição obrigatória)
- **Resolução**: 1024×512 (1k)
- **Uso**: iluminação baseada em imagem (IBL) para o **modo `realistic`** do
  `render_cardinal_views.py`. Cria reflexos plausíveis em superfícies de
  vidro e gera silhueta visível em materiais translúcidos.

### Como baixar (se o arquivo não estiver aqui)

```bash
curl -L -o studio_small_08_1k.hdr \
  https://dl.polyhaven.org/file/ph-assets/HDRIs/hdr/1k/studio_small_08_1k.hdr
```

### Por que essa HDRI específica

- **Estúdio neutro**: simula condição de fotografia de produto (semelhante
  ao que o app real espera receber do usuário).
- **Sem cores fortes**: não viesa a textura/cor do frasco renderizado.
- **1k é suficiente**: a 512×512 de render output, 1k HDRI já é overkill;
  4k ou 8k só aumentaria tempo de carga sem ganho visual.

### Trocar por outro HDRI

Passe `--hdri-path <caminho>` ao `render_cardinal_views.py` para usar outro.
Qualquer HDRI Poly Haven (todos CC0) funciona — recomenda-se preferir
ambientes interiores/estúdio para benchmark de produto.
