/* Catalog data for Guia da API.html — author knobs only. */
(function (w) {
  function P(name, def, meaning, pos, typ) {
    return { name, def, meaning, pos: pos || 0, typ: typ || "" };
  }

  const STAMPS = [
    { id: "stamp-glow", kind: "glow", family: "stamp", name: "Glow",
      idea: "Halo suave no complemento <code>.glow</code>. Mantém a cor do objeto. <code>color=</code> tinge só o brilho.",
      code: "ship.glow = True\nship.glow = \"cyan\"\nship.glow = Glow(\"cyan\", radius=14)\nText(\"GO\", glow=True)",
      search: "glow brilho halo complemento stamp sprite shape text",
      hosts: ["Sprite", "Shape", "Text"],
      params: [P("color", "segue o objeto", "Só o pigmento do halo", 1), P("radius", "12", "Alcance"), P("sigma", "6", "Desfoque"), P("amount", "1", "Intensidade"), P("alpha", "None", "Opacidade do brilho, 0–1; None = a do color")] },
    { id: "stamp-cheapglow", kind: "glow", family: "stamp", name: "CheapGlow",
      idea: "Um halo mais barato que o Glow: algumas cópias claras somadas em volta, sem desfoque. Prefira em frotas e projéteis. Sem propriedade <code>.cheapglow</code> — vai em <code>.glow</code>.",
      code: "shot.glow = CheapGlow(\"tomato\", radius=8)",
      search: "cheapglow frota projetil complemento sprite shape text",
      hosts: ["Sprite", "Shape", "Text"],
      params: [P("color", "segue o objeto", "Só o pigmento", 1), P("radius", "8", "Alcance do halo, em unidades de design"), P("amount", "1", "Intensidade"), P("alpha", "None", "Opacidade do halo, 0–1; None = a do color"), P("sigma", "0", "Desfoque extra das cópias; 0 = sem filtro (o barato)")] },
    { id: "stamp-shadow", kind: "shadow", family: "stamp", name: "Shadow",
      idea: "Sombra no complemento <code>.shadow</code>. <code>color=</code> tinge só a sombra.",
      code: "c.shadow = True\nc.shadow = Shadow(\"navy\")",
      search: "shadow sombra complemento stamp sprite shape",
      hosts: ["Sprite", "Shape"],
      params: [P("color", "preto suave", "Pigmento da sombra", 1), P("offset", "8", "Número ou (dx, dy)"), P("sigma", "5", "Desfoque"), P("alpha", "None", "Opacidade da sombra, 0–1; None = a do shadow_color"), P("dx", "None", "Deslocamento X; None = usa offset"), P("dy", "None", "Deslocamento Y (y para cima); None = usa offset"), P("shadow_color", "(0, 0, 0, 0.55)", "Tinta RGBA usada quando color não é dado", 0, "cor")] },
    { id: "stamp-hueshift", kind: "hue", family: "stamp", name: "HueShift",
      idea: "Gira o matiz no complemento <code>.hue</code>. Num Shape pintado com imagem, use <code>Texture(shift=HueShift(...))</code>.",
      code: "sprite.hue = True\nsprite.hue = 0.33\nsprite.hue = HueShift(to=\"cyan\")\ntex = Texture(\"tex2.png\", shift=HueShift(to=\"cyan\"))",
      search: "hueshift matiz sprite texture complemento",
      hosts: ["Sprite"],
      params: [P("amount", "—", "Voltas (1 = círculo cheio)", 1), P("to", "—", "Uma cor: gira o matiz até ela (calcula amount sozinho; não use junto com amount=)"), P("live", "False", "True deixa o giro mudar durante o jogo (só Sprite; numa Texture levanta erro)")] },
    { id: "stamp-grayscale", kind: "hue", family: "stamp", name: "Grayscale",
      idea: "Tira a cor no complemento <code>.gray</code> (cinza pela luminância). Compõe com <code>.hue</code>: o matiz gira primeiro, o cinza vem por cima. Não custa desempenho: o Sprite continua sendo desenhado do jeito rápido.",
      code: "sprite.gray = True\nsprite.gray = 0.5\nsprite.gray = Grayscale(0.8)\nsprite.gray = None",
      search: "grayscale gray cinza desaturar dessaturar desligado disabled sprite complemento",
      hosts: ["Sprite"],
      params: [P("amount", "1", "Quanto cinza, 0–1 (1 = todo cinza)", 1)] },
    { id: "stamp-tail", kind: "motion", family: "stamp", name: "Tail",
      idea: "Rastro fantasma no complemento <code>.tail</code>. Sem <code>angle=</code> (ou <code>True</code>) segue o movimento; <code>angle=</code> trava. <code>angle</code> / <code>size</code> / <code>amount</code> aceitam <code>lambda:</code>.",
      code: "c.tail = True\n# sem angle=: segue o movimento\nc.tail = Tail(color=\"gold\", size=1.4, amount=1.15)\nc.tail = Tail(angle=180)\nc.tail = Tail(angle=lambda: c.angle + 180, size=lambda: 1.4, amount=lambda: 1.15)",
      search: "tail rastro fantasma complemento stamp sprite shape lambda",
      hosts: ["Sprite", "Shape"],
      params: [P("color", "—", "Tinge só os fantasmas", 1), P("angle", "segue o movimento", "Omitir = segue; graus / lambda = trava", 2), P("size", "1.2", "Comprimento (número ou lambda)", 3), P("amount", "1", "Opacidade das cópias (número ou lambda)", 4)] },
  ];

  const LOOKS = [
    { id: "visual-neon", kind: "glow", family: "visual", name: "Neon",
      idea: "Brilho + corpo + núcleo. Só Shape. Use em poucos objetos de destaque; para muitos (uma frota, tiros), o complemento <code>.glow</code> é mais barato. <code>flicker</code> é o zumbido do tubo.",
      code: "c.visual = Neon(\"magenta\")\nc.visual = Neon(\"cyan\", flicker=0.6)",
      search: "neon heroi brilho nucleo flicker shape",
      hosts: ["Shape"],
      params: [P("color", "segue o preenchimento", "Tinge o corpo", 1), P("amount", "1", "Força do brilho", 2), P("width", "3", "Espessura do núcleo", 3), P("flicker", "0", "Zumbido do halo. 0 = estático.", 0, "número")] },
    { id: "visual-halo", kind: "glow", family: "visual", name: "Halo",
      idea: "Casca luminosa. Oco por padrão. <code>style=\"pulse\"</code> anima anéis concêntricos por dentro.",
      code: "c.visual = Halo()\nc.visual = Halo(\"cyan\", amount=1.2)\nc.visual = Halo(style=\"fill\")\nc.visual = Halo(style=\"pulse\", rings=3)",
      search: "halo casca anel oco pulse",
      hosts: ["Shape", "Sprite"],
      variants: "style",
      params: [P("color", "segue o objeto", "Tinge a casca", 1), P("amount", "1", "Força", 2), P("style", "\"hollow\"", "hollow · fill · soft · line · pulse"), P("rings", "3", "Anéis (só pulse; em outro style é TypeError)"), P("speed", "1", "Ritmo dos anéis (só pulse; em outro style é TypeError)")] },
    { id: "visual-laser", kind: "glow", family: "visual", name: "Laser",
      idea: "Feixe: halo + cor + núcleo branco. Melhor em <code>Line</code>.",
      code: "beam.visual = Laser()\nbeam.visual = Laser(\"lime\")",
      search: "laser raio beam linha",
      hosts: ["Shape", "Sprite"],
      params: [P("color", "segue o traço", "Tinge o feixe", 1), P("amount", "1", "Espessura do feixe, em múltiplos do line_width (2 = o dobro)", 2)] },
    { id: "visual-rim", kind: "glow", family: "visual", name: "Rim",
      idea: "Contorno iluminado: uma borda de luz em volta do objeto, com o miolo levemente escurecido. Destaca a silhueta de um herói ou de um item.",
      code: "c.visual = Rim()\nc.visual = Rim(\"cyan\", amount=1.2)",
      search: "rim contorno highlight",
      hosts: ["Shape", "Sprite"],
      params: [P("color", "segue o objeto", "Cor do contorno", 1), P("amount", "1", "Intensidade da luz (1 = normal, 0 = apagada)", 2), P("width", "4", "Espessura do contorno, em unidades", 3, "número"), P("darken", "0.35", "Quanto o miolo escurece: 0 = nada, 1 = preto", 4, "número")] },
    { id: "visual-bolt", kind: "glow", family: "visual", name: "Bolt",
      idea: "Energia elétrica dentro do corpo — projétil de plasma, orbe de energia. <code>style</code> escolhe o desenho: <code>core</code> (redemoinho no centro), <code>filaments</code> (filamentos girando), <code>tesla</code> (raios do centro à borda, como uma bola de plasma).",
      code: "shot.visual = Bolt(style=\"core\")\nshot.visual = Bolt(style=\"filaments\")",
      search: "bolt raio tesla filaments",
      hosts: ["Shape"],
      variants: "style",
      params: [P("color", "segue o objeto", "Cor da energia", 1), P("amount", "3", "Quantos filamentos (filaments / tesla; em core é TypeError)", 2), P("speed", "1.2", "Ritmo da animação; 0 congela", 3), P("intensity", "0.6 em filaments", "Brilho do contorno", 4), P("style", "\"core\"", "core · filaments · tesla", 5)] },
    { id: "visual-multiborder", kind: "shell", family: "visual", name: "MultiBorder",
      idea: "Várias linhas de contorno em volta do objeto, cada uma um pouco mais afastada e mais larga — como ondas de um alvo.",
      code: "c.visual = MultiBorder()\nc.visual = MultiBorder(layers=3, spread=4)",
      search: "multiborder borda camadas",
      hosts: ["Shape", "Sprite"],
      params: [P("color", "segue o objeto", "Cor das linhas", 1), P("layers", "3", "Quantas linhas", 2, "int"), P("spread", "0.3", "Distância entre as linhas (maior = mais afastadas)", 3, "número")] },
    { id: "visual-organicoutline", kind: "shell", family: "visual", name: "OrganicOutline",
      idea: "Contorno tremido e irregular, como desenhado à mão, que se mexe devagar.",
      code: "c.visual = OrganicOutline()",
      search: "organic outline franja",
      hosts: ["Shape", "Sprite"],
      params: [P("color", "segue o traço", "Cor do traço", 1), P("amount", "2.5", "Quanto o traço treme (0 = liso)", 2), P("speed", "1", "Ritmo do tremor; 0 congela", 3)] },
    { id: "visual-tracer", kind: "shell", family: "visual", name: "Tracer",
      idea: "Um tracejado de luz que corre em volta do contorno — seleção, alvo travado, objeto ativo.",
      code: "c.visual = Tracer()",
      search: "tracer dash trilha",
      hosts: ["Shape", "Sprite"],
      params: [P("color", "segue o objeto", "Cor do tracejado", 1), P("speed", "1", "Velocidade com que os traços correm; 0 para", 2), P("gap", "12", "Espaço entre os traços, em unidades", 3, "número"), P("width", "2.4", "Espessura, em unidades", 4, "número")] },
    { id: "visual-dashring", kind: "shell", family: "visual", name: "DashRing",
      idea: "Dois anéis tracejados girando em volta do objeto, como uma mira ou um radar. Fica melhor em Circle, Ellipse e Line.",
      code: "c.visual = DashRing()",
      search: "dashring anel tracejado",
      hosts: ["Shape", "Sprite"],
      params: [P("color", "segue o objeto", "Cor dos anéis", 1), P("speed", "1", "Velocidade do giro; 0 para", 2), P("width", "2", "Espessura, em unidades", 3, "número")] },
    { id: "visual-gearshell", kind: "shell", family: "visual", name: "GearShell",
      idea: "Uma casca de traços girando em volta do objeto, como uma engrenagem, sobre o corpo suavizado.",
      code: "c.visual = GearShell()\nc.visual = GearShell(color=\"cyan\")",
      search: "gearshell engrenagem casca",
      hosts: ["Shape", "Sprite"],
      params: [P("color", "segue o objeto", "Cor dos traços", 1), P("speed", "1.2", "Velocidade do giro; 0 para", 2), P("amount", "1", "Intensidade (1 = normal, 0 = apagado)", 3)] },
    { id: "visual-electricfield", kind: "shell", family: "visual", name: "ElectricField",
      idea: "Pequenos arcos elétricos piscando em volta da silhueta — eletrificado, sobrecarregado.",
      code: "c.visual = ElectricField()",
      search: "electric field arco",
      hosts: ["Shape", "Sprite"],
      params: [P("color", "segue o objeto", "Cor dos arcos", 1), P("amount", "5", "Quantos arcos", 2), P("speed", "1", "Com que frequência eles mudam", 3)] },
    { id: "visual-electricbolt", kind: "shell", family: "visual", name: "ElectricBolt",
      idea: "Descargas elétricas correndo ao longo do contorno — mais fortes e longas que o ElectricField.",
      code: "c.visual = ElectricBolt(\"gold\")",
      search: "electricbolt descarga",
      hosts: ["Shape", "Sprite"],
      params: [P("color", "segue o objeto", "Cor das descargas", 1), P("amount", "5", "Intensidade das descargas", 2), P("speed", "1", "Com que frequência elas mudam", 3)] },
    { id: "visual-ink", kind: "shell", family: "visual", name: "Ink",
      idea: "Estilo desenho a tinta: o objeto mantém o preenchimento e ganha um contorno de pena que treme de leve.",
      code: "c.visual = Ink()",
      search: "ink tinta pena",
      hosts: ["Shape", "Sprite"],
      params: [P("color", "segue o objeto", "Cor da tinta", 1), P("amount", "1.8", "Quanto o traço treme", 2), P("speed", "0.6", "Ritmo do tremor; 0 congela", 3)] },
    { id: "visual-inkbleed", kind: "shell", family: "visual", name: "InkBleed",
      idea: "Tinta molhada que se espalha pelas bordas, parada (não anima).",
      code: "c.visual = InkBleed()",
      search: "inkbleed sangramento",
      hosts: ["Shape", "Sprite"],
      params: [P("color", "segue o objeto", "Cor da tinta", 1), P("amount", "1", "Quanto a tinta se espalha para fora", 2)] },
    { id: "visual-insertrim", kind: "shell", family: "visual", name: "InsetRim",
      idea: "O preenchimento encolhe para dentro e um contorno fica em volta, com um vão entre os dois.",
      code: "c.visual = InsetRim()",
      search: "insertrim recuo",
      hosts: ["Shape"],
      params: [P("color", "segue o objeto", "Cor do contorno", 1), P("fill_scale", "0.8", "Tamanho do preenchimento encolhido (0.8 = 80%)", 2, "número"), P("width", "6", "Espessura do contorno, em unidades", 3, "número"), P("amount", "0.3", "Intensidade do contorno", 4)] },
    { id: "visual-shield", kind: "orb", family: "visual", name: "Shield",
      idea: "Escudo de energia. Melhor em Circle / Ellipse.",
      code: "orb.visual = Shield()\norb.visual = Shield(\"cyan\")\norb.visual = Shield(style=\"nebula\")",
      search: "shield escudo bubble nebula plasma",
      hosts: ["Shape", "Sprite"],
      variants: "style",
      params: [P("color", "—", "Cor do escudo. bubble: sem ela, a película verde-limão de sempre; com ela, a mesma película nessa cor. bands, vortex e plasma: sem ela, seguem a cor do objeto. Os outros estilos têm cores próprias, e uma cor neles é TypeError", 1), P("style", "\"bubble\"", "bubble · nebula · ember · void · molten · bands · vortex · cracks · frost · plasma"), P("amount", "1", "Intensidade (1 = normal, 0 = apagado)"), P("speed", "1", "Ritmo da animação; 0 congela")] },
    { id: "visual-sphere", kind: "orb", family: "visual", name: "Sphere",
      idea: "Faz um disco parecer uma esfera: luz e sombra dão volume, e o brilho gira devagar. Melhor em Circle.",
      code: "orb.visual = Sphere(\"steel blue\")",
      search: "sphere esfera",
      hosts: ["Shape"],
      params: [P("color", "segue o preenchimento", "Cor da esfera", 1), P("amount", "1", "Quanto volume (0 = chato)"), P("speed", "0.5", "Velocidade do giro da luz; 0 para")] },
    { id: "visual-gel", kind: "orb", family: "visual", name: "Gel",
      idea: "Aparência de bala de goma: translúcido, com brilho e borda mais escura.",
      code: "candy.visual = Gel(\"pink\")",
      search: "gel doce translucido",
      hosts: ["Shape"],
      params: [P("color", "segue o preenchimento", "Cor do doce", 1), P("amount", "1", "Intensidade do efeito (1 = normal)", 2)] },
    { id: "visual-extrude", kind: "element", family: "visual", name: "Extrude",
      idea: "Dá profundidade 3D: o objeto ganha faces laterais que somem rumo a um ponto de fuga, como um bloco visto em perspectiva. O ponto de fuga padrão vale para todos os <code>Extrude</code>: mude com <code>set_extrude_focus(x, y)</code> (padrão: centro da tela). Para um objeto só, passe <code>focus=(x, y)</code> ou fixe a direção com <code>angle=</code>.",
      code: "set_extrude_focus(600, 40)\nship.visual = Extrude(depth=40, layers=5)",
      search: "extrude profundidade",
      thumb: "set_extrude_focus(W * 0.95, H * 0.95)\nship.visual = Extrude(depth=40, layers=5)",
      hosts: ["Shape", "Sprite"],
      params: [P("color", "segue o preenchimento", "Cor", 1), P("depth", "36", "Comprimento das faces, em % da distância até o ponto de fuga", 2, "número"), P("focus", "set_extrude_focus", "Ponto de fuga. Ou set_extrude_focus", 3, "ponto"), P("layers", "5", "Quantas fatias formam a lateral (mais = mais liso, mais caro)", 4, "int"), P("edges", "False", "Contorna as arestas laterais do sólido"), P("darken", "0.42", "Quanto as faces laterais escurecem, 0–1"), P("angle", "None", "Direção fixa da extrusão em graus; None = segue o foco global (set_extrude_focus)")] },
    { id: "visual-metal", kind: "element", family: "visual", name: "Metal",
      idea: "Metal escovado com um aro cromado — placas, moedas, botões de metal. Com cor, corpo e aro ganham a cor (Metal(\"gold\") é ouro com aro dourado).",
      code: "c.visual = Metal()\nc.visual = Metal(\"gold\")\nc.visual = Metal(speed=0)",
      search: "metal cromado",
      hosts: ["Shape", "Sprite"],
      params: [P("color", "cromado", "Cor do metal, no corpo e no aro (sem ela, cromado, qualquer que seja a cor da forma; set_color depois recolore o metal)", 1), P("amount", "1", "Quanto aparece o grão escovado", 2), P("speed", "1", "Ritmo do brilho; 0 congela", 3)] },
    { id: "visual-water", kind: "element", family: "visual", name: "Water",
      idea: "Água vista de lado, com a superfície ondulando em cima. As cores são fixas (não aceita color=).",
      code: "pool.visual = Water()",
      search: "water agua",
      hosts: ["Shape"],
      params: [P("amount", "1", "Ondulação", 1), P("speed", "1", "Tempo", 2)] },
    { id: "visual-swell", kind: "element", family: "visual", name: "Swell",
      idea: "Um fluxo abstrato e lento correndo dentro do objeto, como fumaça ou tinta na água.",
      code: "fx.visual = Swell()",
      search: "swell fluxo",
      hosts: ["Shape", "Sprite"],
      params: [P("amount", "1", "Intensidade (1 = normal, 0 = apagado)", 1), P("speed", "1", "Ritmo; 0 congela", 2)] },
    { id: "visual-flame", kind: "element", family: "visual", name: "Flame",
      idea: "Fogo subindo dentro do objeto. As cores são fixas (não aceita color=).",
      code: "ember.visual = Flame()\nember.visual = Flame(border=True)",
      search: "flame fogo",
      hosts: ["Shape", "Sprite"],
      params: [P("amount", "1", "Turbulência", 1), P("speed", "1.2", "Tempo", 2), P("border", "False", "Aro amarelo", 3)] },
    { id: "visual-wave", kind: "element", family: "visual", name: "Wave",
      idea: "Líquido ondulando dentro do objeto, com uma borda suave.",
      code: "c.visual = Wave()",
      search: "wave onda liquido",
      hosts: ["Shape", "Sprite"],
      params: [P("color", "segue o preenchimento", "Cor", 1), P("amount", "1", "Força", 2), P("speed", "1", "Tempo", 3)] },
    { id: "visual-aurora", kind: "element", family: "visual", name: "Aurora",
      idea: "Faixas de aurora boreal subindo dentro do objeto.",
      code: "c.visual = Aurora()",
      search: "aurora boreal",
      hosts: ["Shape", "Sprite"],
      params: [P("color", "segue o preenchimento", "Cor", 1), P("amount", "1", "Força", 2), P("speed", "0.9", "Tempo", 3)] },
    { id: "visual-liquify", kind: "element", family: "visual", name: "Liquify",
      idea: "Cópias moles do objeto oscilam em volta dele, como gelatina. As cópias seguem a cor do corpo.",
      code: "blob.visual = Liquify()\nblob.visual = Liquify(\"orchid\", amount=5)",
      search: "liquify wobble",
      hosts: ["Shape"],
      params: [P("color", "segue o objeto", "Tinge o corpo (e os fantasmas)", 1), P("amount", "3.5", "Quanto as cópias se afastam ao oscilar", 2), P("speed", "1", "Ritmo da oscilação; 0 congela", 3)] },
    { id: "visual-beat", kind: "motion", family: "visual", name: "Beat",
      idea: "O objeto cresce e encolhe num ritmo, como se respirasse. Sem cor, mantém a cor do objeto. <code>color</code> tinge o corpo (só Shape; Sprite mantém seus pixels).",
      code: "c.visual = Beat()\nc.visual = Beat(\"tomato\", amount=0.12)",
      search: "beat pulso escala",
      hosts: ["Shape", "Sprite"],
      params: [P("color", "segue o objeto", "Tinge o corpo (só Shape)", 1), P("amount", "0.08", "Quanto cresce, em fração do tamanho (0.08 = 8%)", 2), P("speed", "1", "Ritmo da respiração", 3)] },
    { id: "visual-recolor", kind: "sprite", family: "visual", name: "Recolor",
      idea: "Troca uma cor da imagem por outra — o mesmo PNG de inimigo em azul e em vermelho. Os pixels perto do matiz <code>key</code> viram o matiz <code>to</code>; o resto fica. Num Sprite (em <code>.visual</code>) ou numa <code>Texture(shift=)</code>. <code>key</code> precisa ter matiz: branco, cinza ou preto dão erro (Recolor não seleciona áreas cinzentas); <code>to</code> pode ser cinza.",
      code: "sprite.visual = Recolor(\"blue\", \"tomato\")\nTexture(\"tex2.png\", shift=Recolor(\"blue\", \"gold\"))",
      search: "recolor paleta sprite texture",
      hosts: ["Sprite"],
      params: [P("key", "\"blue\"", "A cor que vai ser trocada", 1, "cor"), P("to", "\"tomato\"", "A cor nova", 2), P("range", "0.08", "Quão parecidas com key as cores precisam ser para trocar (maior = pega mais tons)", 0, "número"), P("soft", "0.04", "Suaviza a passagem entre trocado e não trocado", 0, "número")] },
    { id: "visual-aura", kind: "sprite", family: "visual", name: "Aura",
      idea: "Uma faixa de luz que acompanha exatamente a silhueta do Sprite, por dentro e por fora da borda, sem traço duro. Só Sprite.",
      code: "sprite.visual = Aura()\nsprite.visual = Aura(\"cyan\", amount=1.2)",
      search: "aura franja sdf sprite",
      hosts: ["Sprite"],
      params: [P("color", "segue o objeto", "Cor da luz", 1), P("amount", "1", "Intensidade (1 = normal, 0 = apagada)", 2), P("width", "0.35", "Largura da faixa, como fração do tamanho")] },
    { id: "visual-emissivebloom", kind: "sprite", family: "visual", name: "EmissiveBloom",
      idea: "As partes claras do Sprite brilham e vazam luz em volta (bloom), como lâmpadas ou olhos acesos. Só Sprite; é caro — use em poucos (heróis, chefes).",
      code: "sprite.visual = EmissiveBloom()\nsprite.visual = EmissiveBloom(intensity=1.6, sigma=12)",
      search: "emissivebloom bloom sprite",
      hosts: ["Sprite"],
      params: [P("intensity", "1.35", "Força do brilho", 1), P("sigma", "10", "Quanto a luz se espalha", 2)] },
  ];

  const TRANSIENTS = [
    { id: "fx-dissolve-out", kind: "life", family: "life", name: "dissolve_out",
      idea: "Cava a silhueta e esconde. Morte / saída. <code>style</code>: noise · vortex · wipe · fade. Substitui qualquer outro verbo de vida.",
      code: "ship.dissolve_out(0.5, style=\"vortex\", on_done=ship.destroy)\nship.dissolve_out(0.45, style=\"wipe\", angle=0)\nship.dissolve_out(0.4, style=\"fade\")",
      search: "dissolve_out morte sair life style noise vortex wipe fade on_done",
      params: [P("duration", "0.5", "Segundos", 1), P("style", "\"noise\"", "noise · vortex · wipe · fade"), P("angle", "0", "Direção em graus (0 = para a direita): de onde o wipe varre; no vortex, para onde o redemoinho puxa"), P("on_done", "None", "Callback ao terminar ou cancelar")] },
    { id: "fx-burn-out", kind: "life", family: "life", name: "burn_out",
      idea: "Queima o corpo e some. Substitui qualquer outro verbo de vida.",
      code: "ship.burn_out(0.55, on_done=ship.destroy)\nship.burn_out(duration=0.55, intensity=1.2)",
      search: "burn_out queimar life on_done intensity",
      params: [P("duration", "0.55", "Segundos", 1), P("intensity", "1", "Força do fogo"), P("on_done", "None", "Callback ao terminar ou cancelar")] },
    { id: "fx-fade-out", kind: "life", family: "life", name: "fade_out",
      idea: "Só alfa e some. Barato. Substitui qualquer outro verbo de vida.",
      code: "ship.fade_out(0.35, on_done=ship.destroy)\nship.fade_out(duration=0.35)",
      search: "fade_out alfa life on_done",
      params: [P("duration", "0.35", "Segundos", 1), P("on_done", "None", "Callback ao terminar ou cancelar")] },
    { id: "fx-implode", kind: "life", family: "life", name: "implode",
      idea: "Colapsa a escala e some. Substitui qualquer outro verbo de vida.",
      code: "ship.implode(0.28, scale_end=0.05, on_done=ship.destroy)",
      search: "implode colapso life on_done",
      params: [P("duration", "0.28", "Segundos", 1), P("scale_end", "0.05", "Escala final", 0, "número"), P("on_done", "None", "Callback ao terminar ou cancelar")] },
    { id: "fx-dissolve-in", kind: "life", family: "life", name: "dissolve_in",
      idea: "Materializa (spawn). Liga <code>visible</code> no começo. <code>style</code>: noise · vortex · wipe · fade. Se o objeto estiver no meio de um efeito de saída (dissolve_out, fade_out…), este o substitui.",
      code: "ship.dissolve_in(0.5, style=\"noise\", on_done=lambda: None)\nship.dissolve_in(0.45, style=\"vortex\")",
      search: "dissolve_in spawn life style noise vortex wipe fade on_done",
      params: [P("duration", "0.5", "Segundos", 1), P("style", "\"noise\"", "noise · vortex · wipe · fade"), P("angle", "0", "Direção em graus (0 = para a direita): de onde o wipe varre; no vortex, para onde o redemoinho puxa"), P("on_done", "None", "Callback ao terminar ou cancelar")] },
    { id: "fx-fade-in", kind: "life", family: "life", name: "fade_in",
      idea: "Aparece no alfa (spawn). Substitui qualquer outro verbo de vida.",
      code: "ship.fade_in(0.35, on_done=lambda: None)\nship.fade_in(duration=0.35)",
      search: "fade_in spawn life on_done",
      params: [P("duration", "0.35", "Segundos", 1), P("on_done", "None", "Callback ao terminar ou cancelar")] },
    { id: "fx-flash", kind: "hit", family: "hit", name: "flash",
      idea: "O objeto fica branco por um instante — o retorno clássico de levar um golpe. Mesmo canal que blink: um substitui o outro.",
      code: "ship.flash(0.12)\nship.flash(0.2, intensity=0.6, on_done=mark_hit)",
      search: "flash hit on_done",
      params: [P("duration", "0.12", "Segundos", 1), P("intensity", "1", "Força"), P("on_done", "None", "Callback ao terminar ou cancelar")] },
    { id: "fx-blink", kind: "hit", family: "hit", name: "blink",
      idea: "Pisca o objeto (some e volta) — o sinal clássico de invencibilidade depois de levar dano. Segundo blink estende; substitui flash.",
      code: "ship.blink(duration=0.8, rate=8)\nship.blink(1.0, rate=6, intensity=1, on_done=clear_iframe)",
      search: "blink iframe on_done",
      params: [P("duration", "0.8", "Segundos", 1), P("rate", "8", "Piscadas por segundo"), P("intensity", "1", "Força"), P("on_done", "None", "Callback ao terminar ou cancelar")] },
    { id: "fx-pulse", kind: "pulse", family: "pulse", name: "pulse_outline",
      idea: "Contorno que expande.",
      code: "ship.pulse_outline(0.25, color=(1, 1, 1, 1))\nship.pulse_outline(0.4, color=\"cyan\", on_done=clear_stun)",
      search: "pulse_outline contorno on_done",
      params: [P("duration", "0.25", "Segundos", 1), P("color", "branco", "Cor do traço"), P("on_done", "None", "Callback ao terminar ou cancelar")] },
    { id: "fx-pop", kind: "pop", family: "pop", name: "pop",
      idea: "O objeto cresce de repente e volta ao tamanho normal. Roda junto com knock.",
      code: "ship.pop()\nship.pop(scale=1.4)\nship.pop(0.3, scale=1.4, on_done=None)",
      search: "pop escala on_done",
      params: [P("duration", "0.18", "Segundos", 1), P("scale", "1.2", "Pico"), P("on_done", "None", "Callback ao terminar ou cancelar")] },
    { id: "fx-knock", kind: "knock", family: "knock", name: "knock",
      idea: "Empurra o desenho. Não mexe na geometria. Empilha com <code>pop</code>. Polar (<code>distance=</code> + <code>angle=</code>) ou cartesiano (<code>dx=</code> / <code>dy=</code>).",
      code: "ship.knock(distance=16, angle=30)\nship.knock(dx=12, dy=-4, on_done=None)",
      search: "knock recuo on_done",
      params: [P("duration", "0.14", "Segundos", 1), P("distance", "—", "Polar, com angle=", 0, "número"), P("angle", "—", "Graus (y-up)"), P("dx", "0", "Ou deslocamento x", 0, "número"), P("dy", "0", "Deslocamento y", 0, "número"), P("on_done", "None", "Callback ao terminar ou cancelar")] },
    { id: "fx-spark", kind: "spark", family: "spark", name: "spark_burst",
      idea: "Faíscas para fora. Nunca esconde. Não é SpatialFx <code>Sparks</code> nem <code>canvas.zap_at</code>.",
      code: "ship.spark_burst(0.35)\nship.spark_burst(amount=1.2, color=(1, 0.92, 0.75, 1), on_done=None)",
      search: "spark_burst faisca on_done",
      params: [P("duration", "0.35", "Segundos", 1), P("amount", "1", "Quantidade"), P("color", "(1, 0.92, 0.75, 1)", "Pigmento das faíscas"), P("on_done", "None", "Callback ao terminar ou cancelar")] },
    { id: "fx-clear", kind: "life", family: "life", name: "clear_transients",
      idea: "Cancela todos os canais e chama o <code>on_done</code> de cada um (o mesmo <code>on_done</code> do fim normal; ele não recebe aviso de que foi cancelado). Em <code>destroy()</code> o cancelamento é igual, mas sem chamar os on_done.",
      code: "ship.clear_transients()",
      search: "clear_transients cancelar limpar on_done",
      thumb: false,
      params: [] },
  ];

const SPATIAL = [
    { id: "spatial-fire", kind: "point", family: "spatial", name: "Fire",
      idea: "Fogo parado num lugar do mundo: fogueira, tocha, escapamento. Dois jeitos: <code>camp</code> / <code>soft</code> são um disco de fogo de raio <code>radius</code>; <code>plume</code> / <code>tongues</code> / <code>embers</code> / <code>blaze</code> são um jato de largura <code>width</code> que sobe na direção <code>angle</code>. <code>blaze</code> é uma coluna volumétrica cara (1–2 na tela numa GPU fraca; em qualidade medium / low ela desenha o <code>plume</code>).",
      code: "Fire()\nFire(center=(200, 150), radius=40)\nFire(center=(200, 150), width=40, style=\"plume\")\nFire(center=(400, 60), width=80, style=\"blaze\")",
      search: "fire fogo camp plume blaze fogueira coluna",
      variants: "style",
      params: [P("center", "centro do design", "Onde fica o fogo (a base do jato). Um lambda segue: center=lambda: nave.center"), P("radius", "45", "Raio do disco, em unidades de design (camp / soft)"), P("style", "\"camp\"", "camp · soft · plume · tongues · embers · blaze"), P("width", "—", "Largura do jato, em unidades de design (plume, tongues, embers, blaze)"), P("length", "—", "Altura do jato. Omitido: proporcional à largura, conforme o estilo"), P("angle", "90", "Para onde o jato aponta, em graus (90 = para cima, 0 = direita)"), P("amount", "1", "Intensidade: 1 = normal, 0 = apagado, 2 = forte"), P("speed", "1.2", "Ritmo da animação; 0 congela"), P("rate", "None", "Partículas por segundo (plume / embers). None = o padrão do estilo"), P("tongues", "5", "Quantas línguas de fogo (style=\"tongues\"), de 3 a 9", 0, "número inteiro")] },
    { id: "spatial-rain", kind: "pad", family: "spatial", name: "Rain",
      idea: "Chuva caindo num retângulo do mundo. É um objeto próprio, não um visual de outro objeto.",
      code: "Rain(p1=(300, 250), p2=(700, 550))\nRain(center=(500, 400), width=400, height=300)\nplatform = Rect(center=(500, 200), width=400, height=40)\nRain.from_rect(platform)",
      search: "rain chuva",
      params: [P("p1", "—", "Canto. Com p2=: cantos opostos"), P("p2", "—", "Canto oposto a p1"), P("center", "—", "Ou retângulo: center=, width=, height="), P("width", "200", "Largura do retângulo"), P("height", "160", "Altura do retângulo"), P("amount", "0.55", "Densidade"), P("color", "None", "Cor das gotas; None = azul-claro padrão")] },
    { id: "spatial-jet", kind: "beam", family: "spatial", name: "Jet",
      idea: "Jato dirigido. Eixo + brasas.",
      code: "Jet(p1=(200, 100), p2=(200, 40), width=14)\nguide = Line(p1=(400, 80), p2=(520, 200))\nJet.from_line(guide, width=12)",
      search: "jet jato",
      params: [P("p1", "—", "Com p2=: segmento"), P("p2", "—", "Fim do segmento"), P("origin", "—", "Ou polar, com angle= e length="), P("angle", "0", "Graus"), P("length", "50", "Alcance"), P("width", "14", "Espessura"), P("amount", "1", "Intensidade do jato"), P("color", "None", "Cor do jato; None = padrão do efeito")] },
    { id: "spatial-sparks", kind: "point", family: "spatial", name: "Sparks",
      idea: "Campo de faíscas contínuo. Não é <code>spark_burst</code> nem <code>canvas.zap_at</code> (flash elétrico no ponto).",
      code: "fx = Sparks(center=(200, 150), radius=32, rate=40)\nfx.after(0.55, fx.destroy)",
      search: "sparks faiscas",
      params: [P("center", "centro do design", "Ponto do campo"), P("radius", "28", "Tamanho do campo"), P("rate", "40", "Partículas / s"), P("amount", "1", "Quantidade / brilho das faíscas"), P("color", "None", "Cor das faíscas; None = padrão do efeito")] },
    { id: "spatial-glowspot", kind: "point", family: "spatial", name: "GlowSpot",
      idea: "Mancha de luz. Colide como um círculo de 0,9 × radius.",
      code: "GlowSpot(center=(200, 150), radius=48, color=\"cyan\")",
      search: "glowspot luz",
      params: [P("center", "centro do design", "Ponto do brilho. Um lambda segue"), P("radius", "56", "Alcance"), P("color", "—", "Cor"), P("amount", "1", "Brilho")] },
    { id: "spatial-orb", kind: "point", family: "spatial", name: "Orb",
      idea: "Disco + coroa. Padrão de sol. Colide pelo raio do disco.",
      code: "Orb()\nOrb(color=\"silver\", glow=1.15, phase=0.15, soft_edge=0.1)",
      search: "orb sol lua",
      params: [P("center", "centro do design", "Ponto do orbe. Um lambda segue"), P("radius", "48", "Corpo, colisão"), P("color", "quente", "Pigmento"), P("glow", "1", "Coroa fora do corpo"), P("phase", "0", "Fase, como a da lua: 0 = cheia, 1 = nova; valores no meio dão um crescente"), P("amount", "1", "Intensidade do orbe")] },
    { id: "spatial-sunburst", kind: "point", family: "spatial", name: "Sunburst",
      idea: "Explosão de sol no mundo. Não é <code>Stars</code> de fundo.",
      code: "Sunburst()\nSunburst(color=\"cyan\")",
      search: "sunburst starburst",
      params: [P("center", "centro do design", "Ponto da explosão. Um lambda segue"), P("radius", "48", "Alcance"), P("color", "branco→âmbar", "Opcional; omite = rampa canônica"), P("amount", "1", "Intensidade"), P("speed", "1", "Velocidade da animação")] },
    { id: "spatial-starburst", kind: "point", family: "spatial", name: "Starburst",
      idea: "Estrela de raios no mundo. Não é <code>Stars</code> de fundo nem Sunburst.",
      code: "Starburst()\nStarburst(center=(200, 150), radius=40, points=5)",
      search: "starburst estrela raios",
      params: [P("center", "centro do design", "Ponto da estrela. Um lambda segue"), P("radius", "40", "Alcance"), P("points", "5", "Raios (≥ 4)"), P("amount", "1", "Força"), P("speed", "1", "Pulso"), P("color", "creme", "Pigmento")] },
    { id: "spatial-warp", kind: "point", family: "spatial", name: "Warp",
      idea: "Vórtice de hiperespaço no mundo. Um disco com raio, num lugar do mundo. Voo de tela cheia: <code>Tunnel</code> / <code>StarFly</code>. Anel de energia: <code>Portal</code>.",
      code: "Warp()\nWarp(center=(400, 220), radius=90, color=\"cyan\")\nWarp(color=\"navy\", color2=\"black\", core=0, into=False)",
      search: "warp hiperespaco vortex tunel",
      params: [
        P("center", "centro do design", "Ponto do vórtice. Um lambda segue"),
        P("radius", "72", "Corpo, colisão"),
        P("color", "azul frio", "Pigmento dos raios"),
        P("color2", "derivado", "Fundo / parede. None = deriva de color"),
        P("amount", "1", "Energia"),
        P("speed", "1", "Voo no túnel. 0 = parado"),
        P("twist", "0.35", "Espiral", 0, "número"),
        P("spokes", "6", "Raios (inteiro 3…24)", 0, "int"),
        P("core", "1", "Núcleo. 0 = oco", 0, "número"),
        P("into", "True", "True = o voo vai para dentro do túnel; False = o voo sai do túnel, para fora", 0, "bool"),
        P("spin", "0", "Giro (independente de speed)"),
        P("glow", "0.8", "Coroa fora do raio")
      ] },
    { id: "spatial-portal", kind: "point", family: "spatial", name: "Portal",
      idea: "Anel de luz turbulenta no mundo. Oco: o raio é o anel. <code>tilt</code> inclina o anel (vira elipse 3D). Não é <code>Warp</code> (disco de vórtice) nem o visual <code>ElectricField</code> (contorno de um shape).",
      code: "Portal()\nPortal(center=(400, 220), radius=80, color=\"magenta\")\nPortal(radius=70, tilt=60, angle=20, chaos=1.6)",
      search: "portal anel ring hoop rift energia",
      params: [
        P("center", "centro do design", "Ponto do anel. Um lambda segue"),
        P("radius", "60", "Raio do anel, colisão"),
        P("color", "azul elétrico", "Cor do anel"),
        P("color2", "derivado", "Segunda cor dos filamentos. None = violeta com a cor padrão; senão, um tom mais claro de color"),
        P("amount", "1", "Brilho"),
        P("speed", "1", "Velocidade. 0 = congelado"),
        P("thickness", "0.25", "Espessura, fração do raio (0.05…1)", 0, "número"),
        P("chaos", "1", "Turbulência: 0 = aro limpo … 2 = selvagem", 0, "número"),
        P("tilt", "0", "Graus de inclinação: 0 = de frente, 80 ≈ de perfil", 0, "número"),
        P("angle", "0", "Direção do eixo da inclinação (graus)", 0, "número"),
        P("glow", "0.8", "Coroa em volta do anel")
      ] },
  ];

  const POST = [
    { id: "post-vignette", kind: "fixed", family: "post", name: "Vignette",
      idea: "Escurece os cantos.", code: "Vignette()\nVignette(amount=0.8, thickness=0.22)", search: "vignette cantos",
      params: [P("amount", "1", "Força", 1, "número"), P("thickness", "0.22", "Fração da borda", 0, "número")] },
    { id: "post-grain", kind: "fixed", family: "post", name: "Grain",
      idea: "Grão de filme.", code: "Grain()\nGrain(amount=0.12)", search: "grain grao",
      params: [P("amount", "0.07", "Opacidade do grão", 1, "número")] },
    { id: "post-fog", kind: "fixed", family: "post", name: "Fog",
      idea: "Névoa pesando embaixo.", code: "Fog()\nFog(amount=0.6, color=\"dim gray\")", search: "fog nevoa",
      params: [P("amount", "0.45", "Densidade", 1, "número"), P("color", "(0.75, 0.82, 0.9)", "Pigmento", 0, "cor"), P("height", "0.55", "Quanto sobe na tela", 0, "número")] },
    { id: "post-bloom", kind: "fixed", family: "post", name: "Bloom",
      idea: "Brilho estourando nas partes claras.",
      code: "bloom = Bloom(intensity=0.8)\nbloom.intensity = 1.0",
      search: "bloom brilho",
      params: [P("intensity", "0.6", "Força", 1, "número"), P("sigma", "10", "Desfoque", 0, "número")] },
    { id: "post-grade", kind: "fixed", family: "post", name: "Grade",
      idea: "Muda a cor da imagem inteira, como um filtro de foto: mais quente, mais fria, sépia, preto e branco, noturna.",
      code: "Grade(\"cool\")",
      search: "grade filmic cool sepia",
      variants: "preset",
      params: [P("preset", "\"filmic\"", "filmic · cool · warm · sepia · bw · duo · night", 1), P("brightness", "0", "Clareia (positivo) ou escurece (negativo) tudo; 0 = como o preset", 0, "número"), P("contrast", "1", "Contraste: 1 = normal, maior = mais forte", 0, "número"), P("saturation", "1", "Força das cores: 1 = normal, 0 = cinza", 0, "número"), P("matrix", "None", "Matriz de cor 4×5 (20 floats) própria; None = usa o preset", 0, "sequência")] },
    { id: "post-chroma", kind: "fixed", family: "post", name: "Chroma",
      idea: "Separa o vermelho, o verde e o azul para os lados, como uma lente barata ou uma tela com defeito.", code: "Chroma()\nChroma(amount=6)", search: "chroma rgb",
      params: [P("amount", "4", "Quanto as cores se separam, em pixels da tela", 1, "número")] },
    { id: "post-pixelate", kind: "fixed", family: "post", name: "Pixelate",
      idea: "Mostra a imagem em blocos grandes, como um jogo antigo em baixa resolução.", code: "Pixelate()\nPixelate(cell=8)", search: "pixelate",
      params: [P("cell", "5", "Tamanho de cada bloco, em pixels da tela", 1, "número")] },
    { id: "post-scanlines", kind: "fixed", family: "post", name: "Scanlines",
      idea: "Linhas horizontais finas sobre a imagem, como numa TV antiga (CRT).", code: "Scanlines()\nScanlines(amount=0.8)", search: "scanlines crt",
      params: [P("amount", "1", "Força", 1, "número")] },
    { id: "post-screenblur", kind: "fixed", family: "post", name: "ScreenBlur",
      idea: "Desfoque da imagem toda.", code: "ScreenBlur()\nScreenBlur(sigma=4)", search: "screenblur",
      params: [P("sigma", "2.5", "Desfoque", 1, "número")] },
    { id: "post-wash", kind: "fixed", family: "post", name: "Wash",
      idea: "Cobre a imagem inteira com uma cor clara e constante enquanto está ligado — um véu branco, vermelho de dano, dourado de calor. Para um clarão de um instante, use <code>canvas.flash</code>.",
      code: "Wash()\nWash(intensity=0)",
      search: "wash bleach", params: [P("intensity", "0.25", "Força do véu: 0 = nada, 1 = só a cor", 1), P("color", "(1, 1, 1)", "Cor do véu; padrão branco")] },
    { id: "post-distantlight", kind: "light", family: "post", name: "DistantLight",
      idea: "Luz de sol: vem de uma direção e ilumina a tela toda por igual, dando relevo aos objetos.",
      code: "DistantLight()\nDistantLight(direction=(-0.55, -0.75), intensity=1.1)",
      search: "distantlight sol",
      params: [
        P("direction", "(-0.55, -0.75)", "De onde a luz vem, no espaço de design", 1, "ponto"),
        P("color", "(1.12, 1.05, 0.92)", "Pigmento", 0, "cor"),
        P("ambient", "0.28", "Luz ambiente", 0, "número"),
        P("intensity", "0.95", "Força", 0, "número"),
        P("specular", "0.35", "Brilho especular", 0, "número")
      ] },
    { id: "post-haze", kind: "anim", family: "post", name: "Haze",
      idea: "Faz a imagem ondular de leve, como ar quente sobre o asfalto ou a vista debaixo d'água. <code>kind</code> escolhe o estilo de partida (<code>haze</code>, <code>heat</code>, <code>underwater</code>); depois de criado, ajuste <code>amount</code> / <code>speed</code>.",
      code: "Haze(kind=\"heat\")",
      search: "haze heat underwater",
      variants: "kind",
      params: [
        P("amount", "do kind", "Força. Omite = default do kind", 1, "número"),
        P("speed", "do kind", "Tempo. Omite = default do kind", 2, "número"),
        P("kind", "\"haze\"", "haze · heat · underwater. Só escolhe defaults na construção."),
        P("bias", "do kind", "Deslocamento médio da ondulação. Omitido: o padrão do kind")
      ] },
    { id: "post-crt", kind: "anim", family: "post", name: "Crt",
      idea: "Imita uma TV antiga de tubo (CRT): imagem curvada nas bordas, cores separadas, linhas horizontais e cantos escuros.",
      code: "Crt()\nCrt(amount=0.8, chroma=1.2, scan=0.9)",
      search: "crt",
      params: [P("amount", "1", "Quanto a imagem curva nas bordas e escurece nos cantos", 1, "número"), P("chroma", "1", "Quanto o vermelho, o verde e o azul se separam", 0, "número"), P("scan", "1", "Força das linhas horizontais", 0, "número")] },
    { id: "post-vortex", kind: "anim", family: "post", name: "Vortex",
      idea: "Torce a imagem num redemoinho em volta de um ponto. Sem <code>target</code>, o centro segue o mouse.", code: "Vortex()", search: "vortex", params: [P("target", "mouse", "Centro do redemoinho: um ponto ou um objeto; omitido = o mouse"), P("amount", "1", "Quanto torce"), P("spin", "1", "Velocidade do giro; 0 = parado")] },
    { id: "post-zoomblur", kind: "anim", family: "post", name: "ZoomBlur",
      idea: "Borrão em raios saindo de um ponto, como um zoom rápido de câmera ou um salto para a velocidade da luz. Sem <code>center</code>, segue o mouse.", code: "ZoomBlur()", search: "zoomblur", params: [P("center", "mouse", "De onde os raios saem: um ponto ou um objeto; omitido = o mouse"), P("amount", "0.5", "Força do borrão")] },
    { id: "post-kaleidoscope", kind: "anim", family: "post", name: "Kaleidoscope",
      idea: "Caleidoscópio: repete uma fatia da imagem em espelhos em volta do centro, girando.", code: "Kaleidoscope()", search: "kaleidoscope",
      params: [P("segments", "8", "Quantas fatias espelhadas", 1), P("zoom", "1", "Aproxima (maior) ou afasta (menor) a imagem", 2), P("spin", "0.15", "Velocidade do giro; 0 = parado", 3)] },
    { id: "post-prism", kind: "anim", family: "post", name: "Prism",
      idea: "Separa as cores da imagem em direções que giram, como luz passando por um prisma.", code: "Prism()\nPrism(amount=0.006)", search: "prism",
      params: [P("amount", "0.004", "Quanto as cores se separam (valores pequenos: 0.002–0.01)", 1, "número")] },
    { id: "post-perspective", kind: "anim", family: "post", name: "Perspective",
      idea: "Inclina a imagem como se a tela fosse vista de lado, puxando para um ponto. Sem <code>target</code>, segue o mouse.",
      code: "Perspective()\nPerspective(amount=0.7, target=(400, 300))",
      search: "perspective",
      params: [P("amount", "0.55", "Quanto inclina", 1, "número"), P("target", "mouse", "Para onde a imagem inclina: um ponto ou um objeto; None = o mouse")] },
    { id: "post-lamp", kind: "light", family: "post", name: "Lamp",
      idea: "Uma lâmpada sobre o jogo: ilumina em volta de um ponto e deixa o resto na penumbra, com brilho nas bordas dos objetos. Sem <code>target</code>, segue o mouse.",
      code: "Lamp()\nLamp(range=400, radius=180)",
      search: "lamp luz",
      params: [
        P("color", "(1.15, 1.05, 0.85)", "Pigmento", 1, "cor"),
        P("radius", "38% do lado curto", "Tamanho da área bem iluminada, em unidades de design (acompanha o zoom)", 0, "número"),
        P("range", "55% do lado curto", "Distância, em unidades de design, a partir da qual não chega luz", 0, "número"),
        P("ambient", "0.16", "Luz ambiente", 0, "número"),
        P("specular", "0.6", "Brilho especular", 0, "número"),
        P("intensity", "1.15", "Força", 0, "número"),
        P("target", "mouse", "Ponto. None = segue o mouse")
      ] },
    { id: "post-spotlight", kind: "light", family: "post", name: "Spotlight",
      idea: "Um holofote: um cone de luz que sai de <code>origin</code> e aponta para <code>target</code>; fora do cone fica escuro.", code: "Spotlight(range=400)", search: "spotlight",
      params: [P("range", "55% do lado curto", "Corte, unidades de design", 0, "número"), P("origin", "None", "De onde a luz sai; None = topo-centro", 0, "ponto"), P("target", "None", "Para onde aponta; None = mouse", 0, "ponto"), P("color", "(1.15, 1.05, 0.85)", "Cor da luz (pode passar de 1 = mais forte)"), P("cone_angle", "34", "Abertura do cone em graus"), P("softness", "14", "Borda suave do cone, em graus"), P("ambient", "0.1", "Luz fora do cone, 0–1"), P("intensity", "1.45", "Força da luz no cone")] },
    { id: "post-godrays", kind: "anim", family: "post", name: "GodRays",
      idea: "Raios de luz saindo das partes claras da imagem em direção a um ponto, como sol entre nuvens.",
      code: "GodRays()\nGodRays(weight=0.15, target=(400, 300))",
      search: "godrays",
      thumb: "GodRays(target=(W * 0.62, H * 0.5))",
      params: [
        P("weight", "0.08", "Força dos raios (maior = raios mais claros)", 1, "número"),
        P("decay", "0.9", "Queda ao longo do raio", 0, "número"),
        P("exposure", "0.8", "Exposição", 0, "número"),
        P("target", "mouse", "Origem dos raios. None = mouse")
      ] },
    { id: "post-motiontrail", kind: "anim", family: "post", name: "MotionTrail",
      idea: "Rastro fantasma de tudo o que se move na tela: os objetos continuam nítidos e deixam uma imagem que esmaece atrás. <code>enabled = False</code> apaga o rastro.",
      code: "MotionTrail()", search: "motiontrail",
      thumb: "ball = Circle(center=(W * 0.1, H * 0.5), radius=36, color=\"gold\")\nball.move_to(W * 0.9, H * 0.5, time=1.6)\nMotionTrail()",
      params: [P("opacity", "1", "Força do rastro (0 = invisível)"), P("fade", "0.9", "Quanto do rastro sobra a cada 1/60 s: 0.85–0.95 dá rastros longos")] },
    { id: "post-colorsweep", kind: "anim", family: "post", name: "ColorSweep",
      idea: "Tinge a imagem com 2–4 cores que mudam ao longo de um eixo (do centro para a borda, da esquerda para a direita ou de cima para baixo), pulsando devagar.",
      code: "ColorSweep()", search: "colorsweep",
      params: [P("axis", "radial", "radial · horizontal · vertical"), P("speed", "1", "Tempo"), P("colors", "None", "2–4 tintas da varredura; None = paleta padrão"), P("amount", "0.55", "Força da mistura"), P("saturation", "0.45", "Saturação das tintas")] },
    { id: "post-colorwash", kind: "anim", family: "post", name: "ColorWash",
      idea: "Plasma colorindo a imagem. Depois da construção, paleta é <code>.colors</code> (não color / color2 / color3).",
      code: "wash = ColorWash()\nwash.colors = (\"gold\", \"cyan\")\nwash.amount = 0.7\nColorWash(\"orchid\", \"cyan\", \"magenta\", amount=0.7)",
      search: "colorwash",
      params: [
        P("color", "orchid", "Primeira cor", 1, "cor"),
        P("color2", "cyan", "Segunda cor", 0, "cor"),
        P("color3", "magenta", "Terceira cor", 0, "cor"),
        P("colors", "—", "Depois da construção: paleta 2–3 cores. Substitui color / color2 / color3."),
        P("amount", "0.55", "Força", 0, "número"),
        P("speed", "0.55", "Tempo", 0, "número"),
        P("saturation", "0.4", "Saturação", 0, "número")
      ] },
    { id: "post-cosmicbloom", kind: "anim", family: "post", name: "CosmicBloom",
      idea: "Manchas de nébula colorindo a imagem, mais brilho estourando nas partes claras.", code: "CosmicBloom()", search: "cosmicbloom",
      params: [P("speed", "1.2", "Tempo"), P("amount", "1", "Força"), P("color", "None", "Primeira tinta da nebulosa; None = padrão"), P("color2", "None", "Segunda tinta; None = padrão"), P("bloom", "0.7", "Força do brilho nos pixels claros"), P("saturation", "0.35", "Saturação do deslocamento de cor")] },
  ];

  // One-shot canvas verbs: fired, decay on their own, never in canvas.effects.
  // kind: screen (whole picture) · point (*_at, at a place) · cover (fade_out / fade_in).
  const IMPACTS = [
    { id: "post-flash", kind: "screen", family: "impact", name: "canvas.flash",
      idea: "Estouro branco. Não é Wash.",
      code: "canvas.flash(0.6)", search: "flash impacto", params: [P("intensity", "0.6", "Força", 1)] },
    { id: "post-shake", kind: "screen", family: "impact", name: "canvas.shake",
      idea: "Treme a câmera por um instante.", code: "canvas.shake(10)", search: "shake", params: [P("amount", "10", "Força da tremida (10 = padrão; maior = mais forte)", 1)] },
    { id: "post-glitch", kind: "screen", family: "impact", name: "canvas.glitch",
      idea: "Falha de imagem de um instante: a tela pula e as cores se separam.", code: "canvas.glitch()\ncanvas.glitch(0.8)", search: "glitch", params: [P("amount", "1", "Força", 1)] },
    { id: "post-ripple", kind: "point", family: "impact", name: "canvas.ripple_at",
      idea: "Onda no ponto. Também <code>ripple_at(info.point)</code> / Graphic. <code>None</code> não faz nada.",
      code: "canvas.ripple_at(x, y, amount=1.0)\ncanvas.ripple_at(info.point)", search: "ripple",
      params: [P("x", "—", "Onde: x, y em dois números, ou um ponto no 1º", 1), P("y", "—", "A coordenada y, junto com x (omita se passou um ponto em x)", 2), P("amount", "1", "Quanto a imagem entorta (e a força da tremida)", 3), P("radius", "tela", "Até onde a onda chega, em unidades de design; omitido = a tela toda", 4), P("shock", "True", "Desenha o anel de choque"), P("flash", "False", "Clarão breve"), P("shake", "True", "Tremida de câmera")] },
    { id: "post-wave", kind: "point", family: "impact", name: "canvas.wave_at",
      idea: "Uma onda de choque em linha reta que parte do ponto na direção de <code>angle</code> e entorta a tela. Aceita o lugar como <code>ripple_at</code>.",
      code: "canvas.wave_at(x, y, angle=0)\ncanvas.wave_at(info.point, angle=90)", search: "wave_at",
      params: [P("x", "—", "Onde: x, y em dois números, ou um ponto no 1º", 1), P("y", "—", "A coordenada y, junto com x (omita se passou um ponto em x)", 2), P("angle", "0", "Graus. 0 = +x", 3), P("amount", "1", "Força da onda / tremida"), P("shock", "True", "Desenha o anel de choque"), P("flash", "False", "Clarão breve"), P("shake", "True", "Tremida de câmera")] },
    { id: "post-explosion", kind: "point", family: "impact", name: "canvas.explosion_at",
      idea: "Bola de fogo grande num ponto, com tremida e ondulação da tela. Aceita x, y, um ponto ou o info de colisão: <code>explosion_at(info)</code> / <code>info.point</code>. <code>None</code> não faz nada.",
      code: "canvas.explosion_at(x, y)\ncanvas.explosion_at(info.point, amount=0.8, shake=False)\ncanvas.explosion_at(info, amount=0.8, shake=False)",
      search: "explosion_at",
      params: [P("x", "—", "Onde: x, y em dois números, ou um ponto no 1º", 1), P("y", "—", "A coordenada y, junto com x (omita se passou um ponto em x)", 2), P("rings", "True", "Anéis"), P("amount", "1.2", "Força; depois de um ponto, passe amount= pelo nome"), P("shock", "True", "Inclui uma ondulação fraca da tela"), P("flash", "False", "Clarão breve"), P("shake", "True", "Tremida de câmera")] },
    { id: "post-burst", kind: "point", family: "impact", name: "canvas.burst_at",
      idea: "Explosão pequena, do tamanho de uma nave, sem tremida nem clarão: dá para disparar muitas ao mesmo tempo. <code>burst_at(ship)</code> usa o centro.",
      code: "canvas.burst_at(x, y, radius=42)\ncanvas.burst_at(ship, radius=36)", search: "burst_at",
      params: [P("x", "—", "Onde: x, y em dois números, ou um ponto no 1º", 1), P("y", "—", "A coordenada y, junto com x (omita se passou um ponto em x)", 2), P("radius", "42", "Alcance. 3º ou radius=", 3), P("amount", "1.2", "Força", 4), P("rings", "False", "Anéis de traço expandindo")] },
    { id: "post-fireworks", kind: "point", family: "impact", name: "canvas.fireworks_at",
      idea: "Estrelas que abrem. Celebração, não bola de fogo. Sem morteiro. Padrão peônia (<code>fall=0</code>); suba <code>fall</code> para salgueiro. Aceita o lugar como <code>explosion_at</code>.",
      code: "canvas.fireworks_at(x, y)\ncanvas.fireworks_at(x, y, color=\"gold\", radius=64)\ncanvas.fireworks_at(x, y, color=\"cyan\", color2=\"white\", fall=1.1)",
      search: "fireworks_at fogos estrela celebração peony willow",
      params: [P("x", "—", "Onde: x, y em dois números, ou um ponto no 1º", 1), P("y", "—", "A coordenada y, junto com x (omita se passou um ponto em x)", 2), P("color", "ouro", "Pigmento das estrelas", 3), P("color2", "branco derivado", "Glitter / pontas. Omite = deriva de color"), P("radius", "64", "Alcance"), P("amount", "1", "Brilho"), P("count", "28", "Estrelas (8–48)"), P("fall", "0", "Gravidade. 0 = peônia; ~1.2 = salgueiro"), P("trail", "0.35", "Rastro")] },
    { id: "post-zap", kind: "point", family: "impact", name: "canvas.zap_at",
      idea: "Faísca elétrica no ponto: núcleo brilhante + raios dentados. Três estilos: <code>spark</code> (impacto + raios curtos), <code>fork</code> (raios longos ramificados), <code>corona</code> (anel elétrico que abre). Não é SpatialFx <code>Sparks</code> (contínuo) nem <code>spark_burst</code> (transiente de shape). Sem shake / warp de tela. Aceita o lugar como <code>explosion_at</code>.",
      code: "canvas.zap_at(x, y)\ncanvas.zap_at(x, y, style=\"fork\", color=\"gold\", radius=40)\ncanvas.zap_at(ship, style=\"corona\", flash=True)\ncanvas.zap_at(info.point, style=\"spark\", amount=1.2)",
      search: "zap_at electric spark fork corona raio raiozinho faisca eletrica tesla bolt",
      variants: "style",
      params: [
        P("x", "—", "Onde: x, y em dois números, ou um ponto no 1º (tupla, Point, Vec2, Graphic, info de colisão). None = não faz nada", 1),
        P("y", "—", "A coordenada y, junto com x (omita se passou um ponto em x). Depois de um ponto, os outros parâmetros vão por nome", 2),
        P("color", "ciano", "Pigmento do brilho e dos raios", 3),
        P("radius", "24", "Alcance em unidades de design (mín. 12)"),
        P("amount", "1", "Brilho / força (cerca de 0.15–2.5)"),
        P("count", "por style", "Quantos raios. Omite: spark 16 · fork 8 · corona 12 (4–36; escala com qualidade)"),
        P("style", "\"spark\"", "spark = impacto + raios curtos · fork = raios ramificados · corona = anel elétrico"),
        P("flash", "False", "True = um clarão branco curto na tela (canvas.flash)", 0, "bool")
      ] },
    { id: "post-hit", kind: "point", family: "impact", name: "canvas.hit_at",
      idea: "Marca de acerto: algo levou o golpe e <strong>continua vivo</strong>. Estrela branca quente + anel fino + faíscas curtas, ~0,2 s. <code>style=\"disc\"</code> é a versão leve: um disco de luz que abre e some, sem faíscas e sem direção. <code>count=0</code> mantém a estrela e o anel, sem faíscas. <code>angle</code> mira as faíscas num cone (90 = para cima); sem <code>angle</code> elas saem para todo lado. O ângulo nunca vem do <code>info</code> — a normal troca de lado com a ordem do <code>@collide</code>. Junte com a reação do corpo (<code>heroi.flash()</code>, <code>heroi.knock(...)</code>). Sem shake / warp; muitos ao mesmo tempo (chefe sob rajada). Aceita o lugar como <code>explosion_at</code>.",
      code: "canvas.hit_at(info, angle=90)\ncanvas.hit_at(x, y)\ncanvas.hit_at(chefe, color=\"cyan\", radius=24)\ncanvas.hit_at(parede, style=\"disc\")\ncanvas.hit_at(escudo, count=0)",
      thumb: "canvas.hit_at(x, y, radius=32)",
      search: "hit_at acerto golpe impacto tiro dano faisca bala chefe boss hit spark disco disc flash clarão leve",
      variants: "style",
      params: [
        P("x", "—", "Onde: x, y em dois números, ou um ponto no 1º (tupla, Point, Vec2, Graphic, info de colisão). None = não faz nada", 1),
        P("y", "—", "A coordenada y, junto com x (omita se passou um ponto em x). Depois de um ponto, os parâmetros vão por nome", 2),
        P("color", "branco quente", "Tom do aro e das faíscas. O núcleo fica branco", 3),
        P("angle", "None", "Direção das faíscas em graus (0 = direita, 90 = cima), cone de ~100°. None = em volta"),
        P("radius", "16", "Tamanho em unidades de design"),
        P("amount", "1", "Brilho / força"),
        P("count", "8", "Faíscas (3–24; escala com qualidade). 0 = estrela e anel, sem faíscas"),
        P("style", "\"star\"", "star = estrela + anel + faíscas · disc = disco de luz, sem faíscas (angle / count dão erro)")
      ] },
    { id: "post-debris", kind: "point", family: "impact", name: "canvas.debris_at",
      idea: "Quebrou em pedaços, <strong>sem fogo</strong>: cacos irregulares voam, giram, encolhem e somem sobre uma poeira. Fosco (não soma luz) — aparece em fundo claro. <code>fall=0</code> flutua (nave, visão de cima); <code>fall≈1</code> cai em arco (plataforma). A cor nunca vem do Graphic; passe <code>color=</code>. Os cacos são só pintura — não colidem. Encadeie com <code>burst_at</code> (nave explodindo) ou <code>hit_at</code> (pedra rachando). Aceita o lugar como <code>explosion_at</code>.",
      code: "canvas.debris_at(x, y)\ncanvas.debris_at(asteroide, color=\"dim gray\", radius=48)\ncanvas.debris_at(caixa, color=\"peru\", fall=1)",
      thumb: "canvas.debris_at(x, y, color=\"peru\", radius=80, count=22)",
      search: "debris_at destrocos cacos pedacos quebrar estilhacos poeira rocha asteroide caixa debris shards",
      params: [
        P("x", "—", "Onde: x, y em dois números, ou um ponto no 1º (tupla, Point, Vec2, Graphic, info de colisão). None = não faz nada", 1),
        P("y", "—", "A coordenada y, junto com x (omita se passou um ponto em x). Depois de um ponto, os parâmetros vão por nome", 2),
        P("color", "cinza pedra", "Cor dos cacos. A poeira é uma mistura mais clara", 3),
        P("radius", "40", "Espalhamento em unidades de design"),
        P("amount", "1", "Força — quão longe os cacos voam"),
        P("count", "14", "Cacos (4–40; escala com qualidade)"),
        P("fall", "0", "Gravidade. 0 = flutua; ~1 = arco para baixo"),
        P("dust", "True", "Nuvem de poeira sob os cacos (some na qualidade low)", 0, "bool")
      ] },
    { id: "post-bubbles", kind: "point", family: "impact", name: "canvas.bubbles_at",
      idea: "Espuma subindo. Também <code>canvas.bubbles()</code> em colunas. Aceita o lugar como <code>explosion_at</code>.",
      code: "canvas.bubbles_at(x, y, color=\"cyan\", count=18)\ncanvas.bubbles_at(info.point, color=\"cyan\")", search: "bubbles",
      params: [P("x", "—", "Onde: x, y em dois números, ou um ponto no 1º", 1), P("y", "—", "A coordenada y, junto com x (omita se passou um ponto em x)", 2), P("color", "—", "Cor", 3), P("count", "18", "Quantas"), P("height", "140", "Subida"), P("amount", "1", "Quantidade / força das bolhas")] },
    { id: "post-fade-out", kind: "cover", family: "cover", name: "canvas.fade_out",
      idea: "Cobre a tela e <strong>segura</strong> até o <code>fade_in</code>. Depois dos widgets (cobre o HUD). Não é post nem impacto. Sem <code>then=</code>.",
      code: "canvas.fade_out(0.5)\ncanvas.fade_out(0.5, color=\"navy\", style=\"wipe\", angle=90)\ncanvas.fade_out(0.5, style=\"iris\", on_done=load_next)",
      search: "fade_out capa wipe iris transicao preto",
      params: [P("duration", "0.5", "Segundos. 0 = na hora", 1), P("color", "preto", "Cor da capa"), P("style", "\"fade\"", "fade · wipe · iris"), P("angle", "0", "Só wipe, graus (0 = +x)"), P("center", "meio da tela", "Só iris, ponto de design"), P("on_done", "None", "Callback ao terminar o tween")] },
    { id: "post-fade-in", kind: "cover", family: "cover", name: "canvas.fade_in",
      idea: "Revela. Sem capa prévia, começa coberta (abertura). Omita color / style para usar os mesmos do <code>fade_out</code>.",
      code: "canvas.fade_in(0.5)\ncanvas.fade_in(0.45, style=\"iris\")",
      search: "fade_in capa uncover abertura",
      params: [P("duration", "0.5", "Segundos. 0 = na hora", 1), P("color", "a do fade_out", "Cor da capa. Omitida: a mesma da capa atual"), P("style", "o do fade_out", "fade · wipe · iris. Omitido: o mesmo do fade_out"), P("angle", "o do fade_out", "Só wipe, graus. Omitido: o mesmo do fade_out"), P("center", "o do fade_out", "Só iris, ponto de design. Omitido: o mesmo do fade_out"), P("on_done", "None", "Callback ao terminar")] },
  ];

  const FLY_PAN = "Desloca o ponto de fuga junto com a câmera (pan). Desligado por padrão.";
  function fieldCam(pan, zoom, rot, panHint) {
    return [
      P("pan_response", String(pan), panHint || "0 = colado na tela. 1 = 1:1 com o mundo"),
      P("zoom_response", String(zoom), "Quanto o zoom da câmera afeta o padrão"),
      P("rotation_response", String(rot), "Fração da rotação da câmera"),
      P("scroll", "(0, 0)", "Deriva em unidades de design / s, independente da câmera"),
      P("enabled", "True", "Esconde o desenho sem tirar da pilha"),
    ];
  }

  const BACKGROUNDS = [
    { id: "bg-sky", kind: "base", family: "field", name: "SkyGradient",
      idea: "Céu em degradê vertical. Vira a base. Último wallpaper ganha. <code>horizon</code> é onde fica a atmosfera (<code>middle</code>) — 0–1, y-up. <code>palette</code> / <code>top</code> / <code>middle</code> / <code>bottom</code> ficam fixos na construção — para mudar a rampa, troque a base. <code>horizon</code> / <code>fade</code> / câmera / <code>enabled</code> valem ao vivo.",
      code: "SkyGradient(\"night\")\nSkyGradient(\"sunset\")\nSkyGradient(\"day\", horizon=0.42)\nSkyGradient(top=\"navy\", middle=\"sky blue\", bottom=\"navy\")",
      search: "skygradient ceu day night sunset dawn dusk space",
      variants: "palette",
      params: [
        P("palette", "\"day\"", "day · dawn · sunset · dusk · night · space · overcast · desert · forest · toxic · ember · ice · underwater. Qualquer top/middle/bottom pula o preset e completa com day.", 1),
        P("top", "do preset", "Cor do zênite (topo da tela). Com middle/bottom, ignora palette."),
        P("middle", "do preset", "Cor da atmosfera, no horizonte."),
        P("bottom", "do preset", "Cor abaixo do horizonte (sólido). Com horizon=0 não entra."),
        P("horizon", "0", "Linha do horizonte (0–1, y-up desde a base). 0 = céu até embaixo (middle na base). Alinhe com Ground."),
        P("fade", "0.003", "Mistura middle → bottom abaixo da linha. 0 = corte seco. Mesmo parâmetro do Ground."),
        ...fieldCam(0, 0, 0)
      ] },
    { id: "bg-wallpaper", kind: "base", family: "field", name: "Wallpaper",
      idea: "A base do fundo: cor, gradient, arquivo de imagem ou texture. Criar já o põe como <code>canvas.background.base</code>. Sem args: preto opaco. String com <code>.</code> ou <code>/</code> é arquivo; senão é cor. Depois de criado, dá para mudar <code>.source</code>, os ajustes de câmera e <code>enabled</code>. <code>fit</code> / <code>tile_mode</code> / <code>scale</code> / <code>tile_size</code> / <code>underlay</code> / <code>filename</code> / <code>image</code> ficam fixos — para mudar, troque <code>.source</code> ou crie outro Wallpaper. Com câmera que anda (<code>pan_response</code> / <code>zoom_response</code>), passe <code>tile_mode=\"mirror\"</code>: sem ele, além da borda da imagem aparece o <code>underlay</code> (preto).",
      code: "Wallpaper(\"navy\")\nWallpaper(Gradient(\"black\", \"navy\", angle=90), pan_response=0.05)\nWallpaper(\"space.jpg\", tile_mode=\"mirror\", pan_response=0.15, zoom_response=0.3)\nWallpaper(\"bg2.png\", fit=\"contain\")\nWallpaper(path, fit=\"tile\", tile_size=200, tile_mode=\"mirror\")",
      search: "wallpaper base cor imagem texture fit tile cover contain",
      params: [
        P("source", "preto", "Nome de cor, tuple, Color, Gradient, Texture, arquivo (str com . ou /) ou Image. Visual / SpatialFx / filtro levantam TypeError.", 1, "cor / Gradient / arquivo / Texture"),
        P("filename", "None", "Em vez de source: caminho. Busca em Arquivos de imagem."),
        P("image", "None", "Em vez de source: skia.Image já carregada."),
        P("fit", "\"cover\"", "Só imagem: cover · contain · stretch · tile"),
        P("tile_mode", "\"decal\"", "Só imagem: o que aparece além da borda quando a câmera anda ou afasta o zoom. decal (nada; aparece o underlay) · clamp (estica a borda) · repeat · mirror (espelha, sem emenda). Omitido: repeat com fit=\"tile\", senão decal. Em tile, clamp vira repeat."),
        P("scale", "1", "Só imagem: zoom extra. Tem que ser > 0."),
        P("tile_size", "¼ do lado menor", "Só imagem / fit=\"tile\": célula em unidades de design. Com outro fit é TypeError."),
        P("underlay", "preto", "Só imagem: cor das faixas que sobram em fit=\"contain\" e de tudo além da borda com tile_mode=\"decal\". None = não pinta as sobras."),
        ...fieldCam(0, 0, 0)
      ] },
    { id: "bg-stars", kind: "ambient", family: "field", name: "Stars",
      idea: "Campo de estrelas. Não é SpatialFx Starburst.",
      code: "Stars()\nStars(pan_response=0.0, density=0.9, scroll=(0.0, -45.0))",
      search: "stars estrelas",
      params: [
        P("color", "azul-claro", "Pigmento das estrelas", 1),
        P("density", "0.8", "Quantidade"),
        P("twinkle", "0", "Cintilação. 0 = estático."),
        P("amount", "1", "Brilho"),
        P("alpha", "1", "Opacidade"),
        ...fieldCam(0.02, 0, 0)
      ] },
    { id: "bg-clouds", kind: "ambient", family: "field", name: "Clouds",
      idea: "Uma faixa de nuvens. Empilhe várias para dar profundidade.",
      code: "Clouds()\nClouds(pan_response=0.1, amount=0.6, speed=0.8)",
      search: "clouds nuvens",
      thumb: "canvas.background = SkyGradient(\"day\")\nClouds()",
      params: [
        P("color", "branco", "Pigmento das nuvens", 1),
        P("amount", "0.45", "Cobertura"),
        P("band", "0.45", "Altura do meio da faixa na tela: 0 = embaixo, 1 = em cima"),
        P("spread", "0.55", "Quão larga a faixa"),
        P("detail", "1", "Quanto detalhe fino as nuvens têm"),
        P("speed", "1", "Deriva intrínseca"),
        P("alpha", "1", "Opacidade"),
        P("res_scale", "0.5", "Placa de baixa resolução. 1 = full."),
        ...fieldCam(0.08, 0.05, 0)
      ] },
    { id: "bg-mist", kind: "ambient", family: "field", name: "Mist",
      idea: "Faixa de neblina. Não é post Haze nem filtro de shape.",
      code: "Mist()\nMist(pan_response=0.2, amount=0.85)",
      search: "mist neblina",
      params: [
        P("color", "cinza", "Pigmento da névoa", 1),
        P("amount", "0.7", "Densidade"),
        P("band", "0.4", "Altura do meio da faixa na tela: 0 = embaixo, 1 = em cima"),
        P("spread", "0.35", "Quão larga a faixa"),
        P("speed", "0.15", "Deriva intrínseca"),
        P("alpha", "0.7", "Opacidade"),
        ...fieldCam(0.2, 0, 0)
      ] },
    { id: "bg-stardust", kind: "ambient", family: "field", name: "Stardust",
      idea: "Poeira espacial suave (várias oitavas), duas cores. Não é Chromadust nem Nebuladust.",
      code: "Stardust()\nStardust(color=\"violet\", color2=\"cyan\", speed=0.3)",
      search: "stardust poeira dust duas cores",
      params: [
        P("color", "violeta", "Primeiro pigmento", 1),
        P("color2", "ciano", "Segundo pigmento"),
        P("amount", "1", "Densidade"),
        P("speed", "0.2", "Deriva intrínseca"),
        P("alpha", "0.7", "Opacidade"),
        P("res_scale", "0.6", "Placa de baixa resolução. 1 = full."),
        ...fieldCam(0.08, 0.1, 0)
      ] },
    { id: "bg-chromadust", kind: "ambient", family: "field", name: "Chromadust",
      idea: "Mesma poeira do Stardust, mas a cor gira: arco-íris HSV sem args, ou qualquer preset / Gradient. <code>reflect</code> faz vai-e-volta na rampa (vermelho→azul→vermelho). Não é o post Chroma.",
      code: "Chromadust()\nChromadust(\"plasma\")\nChromadust(Gradient(\"sunset\"))\nChromadust((\"red\", \"blue\"))\nChromadust((\"red\", \"blue\"), reflect=False)",
      search: "chromadust rainbow gradient paleta hue reflect yoyo poeira chroma",
      params: [
        P("colors", "None", "None = arco-íris. Nome de preset, Gradient, ou sequência de cores.", 1, "None / preset / Gradient / cores"),
        P("amount", "1", "Densidade"),
        P("speed", "0.2", "Deriva intrínseca"),
        P("hue_speed", "0.25", "Velocidade do giro de paleta", 0, "número"),
        P("saturation", "1", "Croma (HSV e paleta)", 0, "número"),
        P("reflect", "True", "True = vai-e-volta na rampa. False = dá a volta (último → primeiro).", 0, "bool"),
        P("alpha", "0.7", "Opacidade"),
        P("res_scale", "0.6", "Placa de baixa resolução. 1 = full."),
        ...fieldCam(0.08, 0.1, 0)
      ] },
    { id: "bg-nebuladust", kind: "ambient", family: "field", name: "Nebuladust",
      idea: "Poeira tipo Stardust, com manchas médias das 3 cores (nébula). Não é Nebula (faixas) nem Chromadust (arco-íris).",
      code: "Nebuladust()\nNebuladust(color=\"violet\", color2=\"teal\", color3=\"rose\")",
      search: "nebuladust nebula poeira espaço dust manchas cores",
      params: [
        P("color", "violeta", "Primeira região", 1),
        P("color2", "ciano", "Segunda região"),
        P("color3", "rosa", "Terceira região", 0, "cor"),
        P("amount", "1", "Densidade"),
        P("speed", "0.2", "Deriva intrínseca"),
        P("alpha", "0.7", "Opacidade"),
        P("res_scale", "0.6", "Placa de baixa resolução. 1 = full."),
        ...fieldCam(0.08, 0.1, 0)
      ] },
    { id: "bg-borealis", kind: "ambient", family: "field", name: "Borealis",
      idea: "Aurora. <code>height</code> desce do topo da tela.",
      code: "Borealis()\nBorealis(height=0.55, color=\"cyan\")",
      search: "borealis aurora",
      params: [
        P("color", "verde", "Pigmento da aurora", 1),
        P("amount", "1", "Intensidade"),
        P("speed", "0.9", "Ondulação"),
        P("height", "0.65", "Alcance vertical a partir do topo (0–1)"),
        P("alpha", "0.85", "Opacidade"),
        ...fieldCam(0.1, 0.15, 0)
      ] },
    { id: "bg-plasma", kind: "ambient", family: "field", name: "Plasma",
      idea: "Manchas de cor que se mexem devagar e cobrem o fundo inteiro.",
      code: "Plasma()\nPlasma(color=\"magenta\", pan_response=0.3)",
      search: "plasma",
      params: [
        P("color", "magenta", "Pigmento", 1),
        P("amount", "1", "Energia"),
        P("speed", "0", "Tempo. 0 = parado."),
        P("alpha", "0.55", "Opacidade"),
        ...fieldCam(0.3, 0.4, 0)
      ] },
    { id: "bg-debris", kind: "ambient", family: "field", name: "Debris",
      idea: "Farrapos / detritos. Campo de tela cheia, não partículas SpatialFx.",
      code: "Debris()\nDebris(density=0.9, drift=0.6)",
      search: "debris",
      params: [
        P("color", "cinza", "Pigmento", 1),
        P("density", "0.7", "Quantidade"),
        P("scale", "1", "Tamanho do padrão"),
        P("drift", "0.4", "Deriva intrínseca"),
        P("alpha", "0.75", "Opacidade"),
        ...fieldCam(0.35, 0.15, 0)
      ] },
    { id: "bg-embers", kind: "ambient", family: "field", name: "Embers",
      idea: "Cinzas subindo. Campo ambiente; ≠ SpatialFx Fire.",
      code: "Embers()\nEmbers(color=\"orange\", density=0.9, rise=1.1)",
      search: "embers cinzas",
      params: [
        P("color", "laranja", "Pigmento", 1),
        P("density", "1.1", "Quantidade"),
        P("rise", "0.8", "Subida"),
        P("alpha", "0.95", "Opacidade"),
        ...fieldCam(0.4, 0.1, 0)
      ] },
    { id: "bg-wind", kind: "ambient", family: "field", name: "WindStreaks",
      idea: "Rastros de vento (cabeça brilhante + glow). <code>angle</code> em graus; 0 = horizontal.",
      code: "WindStreaks()\nWindStreaks(angle=15, density=0.8, length=1.8)",
      search: "windstreaks vento",
      params: [
        P("color", "azul-claro", "Pigmento", 1),
        P("density", "0.65", "Quantidade"),
        P("length", "1.4", "Comprimento do rastro"),
        P("angle", "0", "Graus. 0 = horizontal."),
        P("speed", "1.3", "Velocidade"),
        P("glow", "0.9", "Halo"),
        P("alpha", "0.8", "Opacidade"),
        ...fieldCam(0.85, 0.2, 0)
      ] },
    { id: "bg-ground", kind: "ambient", family: "field", name: "Ground",
      idea: "Faixa de chão ortográfica. Transparente acima de <code>horizon</code> (a linha do horizonte). Alinhe com SkyGradient. <code>horizon</code> / <code>fade</code> valem ao vivo.",
      code: "Ground(horizon=0.42)\nGround(color=\"olive\", horizon=0.42, detail=0.4)",
      search: "ground chao",
      params: [
        P("color", "verde-oliva", "Pigmento do chão (escurece para baixo)", 1),
        P("edge", "derivado de color", "Tinta do horizonte. Omite = versão mais clara de color.", 0, "cor"),
        P("horizon", "0.42", "Linha do horizonte (0–1, y-up desde a base). Mesmo valor do SkyGradient."),
        P("fade", "0.003", "Mistura na linha do horizonte. 0 = corte seco. Mesmo parâmetro do SkyGradient."),
        P("detail", "0", "Grão. 0 = preenchimento plano."),
        P("line", "1", "Força do grão"),
        P("alpha", "1", "Opacidade"),
        ...fieldCam(0.9, 0, 0)
      ] },
    { id: "bg-lattice", kind: "ambient", family: "field", name: "Lattice",
      idea: "Grade suave de células. É transparente entre as linhas, então dá para pôr sobre outros fundos.",
      code: "Lattice()\nLattice(fold=\"hex\", layers=3)\nLattice(fold=\"square\", edge=\"fill\", color=\"red\")",
      search: "lattice grade hex",
      variants: "fold, edge",
      params: [
        P("fold", "\"hex\"", "square · hex · tri", 1),
        P("edge", "\"outline\"", "outline · fill", 0, "str"),
        P("color", "verde-água", "Pigmento"),
        P("spacing", "1", "Passo entre centros das células"),
        P("size", "1", "Extensão da forma na célula (máx 1.7)"),
        P("line", "1", "Espessura do traço"),
        P("layers", "1", "1–3 grades sobrepostas; em hex, as extras ficam nos vértices."),
        P("layer_scale", "1", "Tamanho das camadas filhas (1–2)"),
        P("angle", "0", "Giro da grade, em graus"),
        P("alpha", "0.55", "Opacidade"),
        ...fieldCam(0.25, 0.35, 0)
      ] },
    { id: "bg-nebula", kind: "ambient", family: "field", name: "Nebula",
      idea: "Faixas de poeira largas. Prima de Stardust, mais barata. Não é Shield style=\"nebula\".",
      code: "Nebula()\nNebula(color=\"purple\", color2=\"navy\", contrast=1.2)",
      search: "nebula",
      params: [
        P("color", "violeta", "Primeiro pigmento", 1),
        P("color2", "azul", "Segundo pigmento"),
        P("scale", "1", "Tamanho do padrão"),
        P("contrast", "1", "Contraste das faixas"),
        P("speed", "0.15", "Deriva intrínseca"),
        P("alpha", "0.55", "Opacidade"),
        ...fieldCam(0.06, 0.08, 0)
      ] },
    { id: "bg-churn", kind: "ambient", family: "field", name: "ChurningClouds",
      idea: "Nuvens de espaço que se revolvem e respiram no lugar.",
      code: "ChurningClouds()\nChurningClouds(alpha=0.65, speed=0.5, contrast=1.2)",
      search: "churningclouds",
      params: [
        P("color", "azul", "Primeiro pigmento", 1),
        P("color2", "rosa", "Segundo pigmento"),
        P("amount", "1", "Densidade"),
        P("speed", "0.4", "Ritmo do redemoinho; 0 = parado"),
        P("scale", "1", "Tamanho do padrão"),
        P("contrast", "1", "Contraste"),
        P("alpha", "0.6", "Opacidade"),
        P("seed", "0", "Semente do ruído"),
        P("res_scale", "0.4", "Placa de baixa resolução. 1 = full."),
        ...fieldCam(0.06, 0.08, 0)
      ] },
    { id: "bg-filament", kind: "ambient", family: "field", name: "FilamentField",
      idea: "Filamentos com deriva lenta e surtos pontuais.",
      code: "FilamentField()\nFilamentField(color=\"cyan\", alpha=0.45, contrast=1.3)",
      search: "filamentfield",
      params: [
        P("color", "ciano", "Pigmento", 1),
        P("amount", "1", "Densidade"),
        P("speed", "0.35", "Deriva intrínseca"),
        P("contrast", "1", "Contraste dos filamentos"),
        P("alpha", "0.55", "Opacidade"),
        P("seed", "0", "Semente do ruído"),
        P("res_scale", "0.5", "Placa de baixa resolução. 1 = full."),
        ...fieldCam(0.18, 0.08, 0)
      ] },
    { id: "bg-floor", kind: "fly", family: "field", name: "Floor",
      idea: "Chão infinito em perspectiva, como nos jogos de corrida antigos: grade e xadrez, névoa no horizonte.",
      code: "canvas.set_fly(Floor())\ncanvas.set_fly(Floor(speed=1.2, grid=0.9, fog=0.4))",
      search: "floor mode7",
      params: [
        P("color", "verde", "Pigmento do chão", 1),
        P("sky", "quase-preto", "Cor acima do horizonte"),
        P("amount", "1", "Contraste do padrão"),
        P("speed", "1", "Voo intrínseco"),
        P("grid", "0.75", "Visibilidade da grade"),
        P("fog", "0.55", "Névoa no horizonte"),
        P("alpha", "1", "Opacidade"),
        ...fieldCam(0, 0, 0)
      ] },
    { id: "bg-road", kind: "fly", family: "field", name: "Road",
      idea: "Estrada em perspectiva para jogo de rolagem lateral: só pan / scroll horizontal. O horizonte não sobe.",
      code: "canvas.set_fly(Road())\ncanvas.set_fly(Road(speed=1.4, pan_response=0.85))",
      search: "road estrada",
      params: [
        P("color", "marrom", "Pigmento da pista", 1),
        P("sky", "azul-noite", "Cor acima do horizonte"),
        P("amount", "1", "Contraste do padrão"),
        P("speed", "1", "Voo intrínseco"),
        P("grid", "0.7", "Visibilidade da grade"),
        P("fog", "0.5", "Névoa no horizonte"),
        P("alpha", "1", "Opacidade"),
        ...fieldCam(0.85, 0, 0)
      ] },
    { id: "bg-tunnel", kind: "fly", family: "field", name: "Tunnel",
      idea: "Túnel de estrias a tela cheia. Vórtice no mundo: SpatialFx <code>Warp</code>. Prefira <code>canvas.set_fly(Tunnel())</code>.",
      code: "canvas.set_fly(Tunnel())\ncanvas.set_fly(Tunnel(speed=1.4, density=1.2, center=(200, 0)))",
      search: "tunnel tunel",
      params: [
        P("color", "branco-azulado", "Pigmento das estrias", 1),
        P("amount", "1", "Brilho"),
        P("speed", "1", "Voo. Prefira speed para imersão."),
        P("density", "1", "Quantidade de estrias"),
        P("streak", "1", "Comprimento da estria"),
        P("alpha", "1", "Opacidade"),
        P("center", "None", "Ponto de fuga no espaço de design. None = centro da tela."),
        ...fieldCam(0, 0, 0, FLY_PAN)
      ] },
    { id: "bg-starfly", kind: "fly", family: "field", name: "StarFly",
      idea: "Estrelas-ponto voando na cara (screensaver). ≠ Stars plano, ≠ Tunnel de estrias.",
      code: "canvas.set_fly(StarFly())\ncanvas.set_fly(StarFly(speed=1.5, density=1.2, center=(200, 0)))",
      search: "starfly",
      params: [
        P("color", "branco", "Pigmento", 1),
        P("amount", "1", "Brilho"),
        P("speed", "1", "Voo"),
        P("density", "1", "Quantidade"),
        P("alpha", "1", "Opacidade"),
        P("center", "None", "Ponto de fuga no espaço de design. None = centro da tela."),
        ...fieldCam(0, 0, 0, FLY_PAN)
      ] },
    { id: "bg-planetfly", kind: "fly", family: "field", name: "PlanetFly",
      idea: "Sobrevoo com horizonte curvo. <code>roll=\"into\"</code> entra na tela; <code>\"side\"</code> é side-scroller.",
      code: "canvas.set_fly(PlanetFly())\ncanvas.set_fly(PlanetFly(roll=\"side\", speed=1.2, fog=0.35))",
      search: "planetfly planeta",
      params: [
        P("color", "verde-terra", "Pigmento do solo", 1),
        P("space", "quase-preto", "Cor do espaço acima do horizonte"),
        P("amount", "1", "Contraste do relevo"),
        P("bright", "1.15", "Visibilidade do solo"),
        P("speed", "1", "Voo"),
        P("relief", "0.9", "Relevo"),
        P("fog", "0.45", "Névoa no horizonte"),
        P("size", "0.55", "Escala do planeta no quadro"),
        P("roll", "\"into\"", "into / forward = entra; side / lateral = rola R→L"),
        P("alpha", "1", "Opacidade"),
        ...fieldCam(0, 0, 0)
      ] },
  ];

  const FILTERS = [
    { id: "filter-blur", kind: "filter", family: "filter", name: "Blur",
      idea: "Desfoca o interior ou o contorno do objeto (conforme vá em <code>fill_filter</code> ou <code>line_filter</code>).",
      code: "c.fill_filter = Blur()\nc.fill_filter = Blur(sigma=4)",
      search: "blur desfoque",
      params: [P("sigma", "4", "Quanto desfoca, em unidades (0 = nítido)", 1), P("sigmaX", "None", "Desfoque só no eixo X; None = sigma"), P("sigmaY", "None", "Desfoque só no eixo Y; None = sigma"), P("tile_mode", "\"decal\"", "Borda: decal · clamp · repeat · mirror"), P("input", "None", "filtro de entrada (encadeia filtros); None = a própria forma", 0, "filtro")] },
    { id: "filter-glowfilter", kind: "filter", family: "filter", name: "GlowFilter",
      idea: "Um halo de luz em volta do interior ou do contorno. Para muitos objetos, crie um só e use em todos (<code>halo = GlowFilter(); a.fill_filter = halo; b.fill_filter = halo</code>). O brilho comum de um objeto é o complemento <code>.glow</code>.",
      code: "c.fill_filter = GlowFilter(radius=10, sigma=5)",
      search: "glowfilter filtro halo",
      params: [P("radius", "12", "Até onde o halo chega, em unidades"), P("sigma", "10", "Quanto o halo é borrado"), P("intensity", "1", "Força do brilho"), P("color", "(1, 0.95, 0.65, 1)", "Cor do halo (padrão: amarelo-claro)"), P("input", "None", "filtro de entrada (encadeia filtros); None = a própria forma", 0, "filtro")] },
    { id: "filter-hostglow", kind: "filter", family: "filter", name: "HostGlow",
      idea: "Um halo na própria cor de cada objeto: o mesmo filtro em naves de cores diferentes dá a cada uma o seu brilho.",
      code: "c.fill_filter = HostGlow()\nc.fill_filter = HostGlow(sigma=4, spread=2)",
      search: "hostglow filtro halo host",
      params: [P("sigma", "3.5", "Quanto o halo é borrado", 1), P("spread", "0", "Engrossa o halo antes de borrar (unidades)", 2), P("input", "None", "filtro de entrada (encadeia filtros); None = a própria forma", 0, "filtro")] },
    { id: "filter-emissive", kind: "filter", family: "filter", name: "EmissiveFilter",
      idea: "Faz as partes claras do objeto brilharem e vazarem luz em volta (bloom), no interior (<code>fill_filter</code>) ou no contorno (<code>line_filter</code>). Para um Sprite, o visual pronto é <code>EmissiveBloom</code>.",
      code: "sprite.fill_filter = EmissiveFilter(intensity=1.4, sigma=10)",
      search: "emissivefilter bloom filtro",
      params: [P("intensity", "1.35", "Força", 1), P("sigma", "10", "Desfoque", 2), P("input", "None", "filtro de entrada (encadeia filtros); None = a própria forma", 0, "filtro")] },
    { id: "filter-dropshadow", kind: "filter", family: "filter", name: "DropShadow",
      idea: "Sombra. y-up: padrão cai para baixo-direita. Complemento: <code>.shadow</code>.",
      code: "c.fill_filter = DropShadow(offset=12, sigma=8)",
      search: "dropshadow sombra filtro",
      params: [P("offset", "(8, -8)", "Número ou (dx, dy)"), P("sigma", "5", "Desfoque"), P("color", "(0, 0, 0, 0.55)", "Pigmento"), P("dx", "None", "Deslocamento X; None = usa offset"), P("dy", "None", "Deslocamento Y (y para cima); None = usa offset"), P("input", "None", "filtro de entrada (encadeia filtros); None = a própria forma", 0, "filtro")] },
    { id: "filter-dilate", kind: "filter", family: "filter", name: "Dilate",
      idea: "Expande a silhueta.",
      code: "c.fill_filter = Dilate(radius=3)",
      search: "dilate expandir",
      params: [P("radius", "4", "Alcance", 1), P("radiusX", "None", "Raio só no eixo X; None = radius"), P("radiusY", "None", "Raio só no eixo Y; None = radius"), P("input", "None", "filtro de entrada (encadeia filtros); None = a própria forma", 0, "filtro")] },
    { id: "filter-erode", kind: "filter", family: "filter", name: "Erode",
      idea: "Encolhe a silhueta.",
      code: "c.fill_filter = Erode(radius=3)",
      search: "erode encolher",
      params: [P("radius", "2.5", "Alcance", 1), P("radiusX", "None", "Raio só no eixo X; None = radius"), P("radiusY", "None", "Raio só no eixo Y; None = radius"), P("input", "None", "filtro de entrada (encadeia filtros); None = a própria forma", 0, "filtro")] },
    { id: "filter-compose", kind: "filter", family: "filter", name: "ComposeFx",
      idea: "Dois filtros, um em volta do outro.",
      code: "c.fill_filter = ComposeFx(Blur(2), DropShadow())",
      search: "composefx compose",
      params: [P("outer", "—", "Filtro de fora", 1), P("inner", "—", "Filtro de dentro", 2)] },
  ];

  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // Inside an attribute value: also quotes (a variant's code is Halo(style="pulse")).
  function escAttr(s) {
    return esc(s).replace(/"/g, "&quot;");
  }

  function ordinal(n) { return n + "º"; }

  const FAMILY_LABEL = {
    visual: "look",
    spatial: "spatial",
    post: "post",
    impact: "impacto",
    field: "material",
    filter: "filter",
    stamp: "complemento",
    life: "transient",
    knock: "transient",
    exit: "transient",
    enter: "transient",
    hit: "transient",
    pulse: "transient",
    pop: "transient",
    spark: "transient",
    cover: "capa",
  };

  function familyLabel(item) {
    return FAMILY_LABEL[item.family] || item.family || "";
  }

  const HOST_ORDER = ["Sprite", "Shape", "Text"];
  const HOST_ORDER_VISUAL = ["Shape", "Sprite"];

  function hostChips(item) {
    if (!item.hosts) return "";
    const set = new Set(item.hosts);
    const order = (item.family === "stamp" || set.has("Text"))
      ? HOST_ORDER
      : HOST_ORDER_VISUAL;
    const yes = order.filter((h) => set.has(h));
    const chips = order.map((h) => {
      const on = set.has(h);
      return `<span class="host ${on ? "yes" : "no"}">${esc(h)}</span>`;
    }).join("");
    const label = (order === HOST_ORDER_VISUAL && yes.length === 2)
      ? "Shape e Sprite"
      : (yes.join(", ") || "nenhum");
    return `<span class="hosts" aria-label="Aplicável a ${label}">${chips}</span>`;
  }

  function sigHint(params) {
    const hasPos = params.some((p) => p.pos);
    const hasKw = params.some((p) => !p.pos);
    if (hasPos && hasKw) {
      return "Nome sem <code>=</code>: 1º, 2º… na ordem. Nome com <code>=</code>: pelo nome.";
    }
    if (hasPos) return "Nome sem <code>=</code>: 1º, 2º… na ordem.";
    return "Nome com <code>=</code>: passe pelo nome.";
  }

  function inferType(p) {
    if (p.typ) return p.typ;
    const n = p.name;
    const byName = {
      color: "cor", to: "cor", color2: "cor", color3: "cor", underlay: "cor",
      top: "cor", middle: "cor", bottom: "cor", sky: "cor", space: "cor",
      key: "cor",
      live: "bool", only_int: "bool", show_value: "bool", centered: "bool",
      use_center: "bool", enabled: "bool", rings: "bool", border: "bool",
      into: "bool", reflect: "bool", flash: "bool",
      on_done: "() → None",
      at: "ponto / (() → ponto)",
      style: "str", preset: "str", kind: "str", fit: "str", tile_mode: "str",
      wrap: "str", family: "str", palette: "str", source: "str", label: "str",
      name: "str", axis: "str", fold: "str", roll: "str", filename: "str",
      colors: "sequência",
      center: "ponto", p1: "ponto", p2: "ponto", origin: "ponto", focus: "ponto",
      offset: "número / ponto", scroll: "ponto", target: "ponto",
      n: "int", points: "int", cols: "int", rows: "int", layers: "int",
      count: "int", segments: "int", spokes: "int",
      outer: "filtro", inner: "filtro", image: "Image",
    };
    if (byName[n]) return byName[n];
    if (/^(radius|sigma|amount|speed|width|height|length|intensity|duration|fps|scale|angle|min_value|max_value|density|rate|spread|glow|phase|soft_edge|x|y|x1|y1|x2|y2|pan_response|zoom_response|rotation_response|alpha|size|tile_size|opacity|fade|zoom|spin|fall|trail|horizon|twinkle|band|detail|drift|rise|spacing|layer_scale|line|contrast|grid|fog|streak|bright|relief|seed|res_scale|flicker|darken|gap|fill_scale|depth|range|soft|scale_end|distance|dx|dy|twist|core|hue_speed|saturation|thickness|cell|weight|decay|exposure|ambient|specular|brightness|bias)$/.test(n)) {
      return "número";
    }
    return "";
  }

  function identOk(name) {
    return /^[A-Za-z_][A-Za-z0-9_]*$/.test(name);
  }

  function signatureLine(item) {
    item.params.forEach((p) => {
      if (!identOk(p.name)) {
        console.warn("Guia: parâmetro com nome inválido em " + item.name + ": " + p.name);
      }
      if (!inferType(p)) {
        console.warn("Guia: parâmetro sem tipo em " + item.name + "." + p.name);
      }
    });
    const inner = item.params.map((p) => p.pos ? p.name : p.name + "=").join(", ");
    return item.name + "(" + inner + ")";
  }

  // A coluna Tipo mostra o tipo + o valor default do construtor (não mais um
  // exemplo arbitrário). Quando o default não é um literal simples (depende do
  // contexto: "segue o objeto", "o do fade_out", …), o texto descritivo já serve de
  // exemplo e fica nesse mesmo espaço.
  function typeCell(p) {
    const typ = inferType(p);
    const def = p.def && p.def !== "—" ? `<span class="ex">${esc(p.def)}</span>` : "";
    return `<td class="type"><span class="t">${esc(typ)}</span>${def}</td>`;
  }

  function paramRows(params) {
    return params.map((p) =>
      `<tr><td><code>${esc(p.name)}</code></td><td>${p.pos ? ordinal(p.pos) : "nome="}</td>${typeCell(p)}<td>${p.meaning}</td></tr>`
    ).join("");
  }

  function renderPanel(item, active) {
    let details = "";
    if (item.params && item.params.length) {
      details = `<details class="spec" open><summary>Parâmetros</summary>
        <p class="sig"><code>${esc(signatureLine(item))}</code></p>
        <p class="sig-hint">${sigHint(item.params)}</p>
        <div class="tbl-wrap"><table>
        <thead><tr><th>Parâmetro</th><th>Passar</th><th>Tipo (default)</th><th>Significado</th></tr></thead>
        <tbody>${paramRows(item.params)}</tbody></table></div></details>`;
    } else if (item.params) {
      details = `<details class="spec" open><summary>Parâmetros</summary>
        <p class="sig"><code>${esc(item.name)}()</code></p>
        <p class="sig-hint">Sem parâmetros.</p></details>`;
    }
    const on = active ? " active" : "";
    const fam = familyLabel(item);
    const hosts = hostChips(item);
    const chip = !hosts && fam ? `<span class="family">${esc(fam)}</span>` : "";
    const hostAttr = item.hosts && item.hosts.length
      ? ` data-hosts="${esc(item.hosts.join(" "))}"`
      : "";
    const text = `<p class="one-liner">${item.idea}</p>
      <div class="code-panel"><button class="copy-btn" type="button">copiar</button><pre>${esc(item.code)}</pre></div>`;
    const th = thumbOf(item);
    const body = th
      ? `<div class="catalog-body"><div class="catalog-text">${text}</div>
        <figure class="thumb"><div class="thumb-frame">${thumbImg(item, th, "lazy")}${playButton(th)}</div>
        <figcaption class="thumb-code" hidden><code></code></figcaption></figure></div>${variantStrips(item, th)}`
      : text;
    return `<div class="tab-panel${on}" data-panel="${item.id}" id="${item.id}" data-kind="${item.kind}"${hostAttr}>
      <div class="catalog-meta">${chip}${hosts}</div>
      ${body}
      ${details}
    </div>`;
  }

  // ── Thumbnails (guia-api-thumbs.js, made by make_guia_thumbs.py) ──
  // A card with a picture shows it next to its code; a catalog with pictures
  // also gets a gallery view. No thumbs file → the text-only catalog of old.

  function thumbOf(item) {
    const all = w.ScenaGuideThumbs;
    return all && all[item.id] ? all[item.id] : null;
  }

  // ``small``: the gallery picture (reduced from the full render, so stars and
  // thin lights survive; the browser shrinking the 480 px poster erased them).
  function thumbImg(item, th, loading, small) {
    const anim = th.anim ? ` data-anim="${esc(th.anim)}"` : "";
    const src = small && th.card ? th.card : th.src;
    const tall = th.h > th.w ? " data-tall" : "";
    return `<img src="${esc(src)}" data-static="${esc(src)}"${anim}${tall} width="${th.w}" height="${th.h}" loading="${loading}" alt="Prévia de ${esc(item.name)}">`;
  }

  function playButton(th) {
    return `<button class="thumb-play" type="button" aria-pressed="false" aria-label="Animar"${th.anim ? "" : " hidden"}>▶</button>`;
  }

  // One strip per varied parameter: every value the code accepts, as pictures.
  function variantStrips(item, th) {
    if (!th.variants || !th.variants.length) return "";
    const byParam = {};
    th.variants.forEach((v) => { (byParam[v.param] = byParam[v.param] || []).push(v); });
    return Object.keys(byParam).map((param) => {
      const cards = byParam[param].map((v) => {
        const anim = v.anim ? ` data-anim="${esc(v.anim)}"` : "";
        return `<button class="v-card" type="button" aria-pressed="false" data-src="${escAttr(v.src)}" data-w="${v.w}" data-h="${v.h}"${anim} data-code="${escAttr(v.code)}" title="${escAttr(v.code)}">
          <img src="${escAttr(v.card || v.src)}" width="${v.w}" height="${v.h}" loading="lazy" alt="${escAttr(v.code)}"><span>${esc(v.value)}</span></button>`;
      }).join("");
      return `<div class="variants" role="group" aria-label="${esc(item.name)} ${esc(param)}=">
        <span class="v-param"><code>${esc(param)}=</code></span><div class="v-row">${cards}</div></div>`;
    }).join("");
  }

  function reducedMotion() {
    return !!(w.matchMedia && w.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }

  // A loop plays when the reader asked for it (▶), or on its own where the
  // eye is, unless the system asks for reduced motion. The reader's ▶ / ❚❚
  // always wins: reduced motion stops autoplay, not a requested animation.
  function setPlaying(img, auto) {
    if (!img) return;
    const btn = img.parentElement && img.parentElement.querySelector(".thumb-play");
    if (!img.dataset.anim) {
      if (img.getAttribute("src") !== img.dataset.static) img.setAttribute("src", img.dataset.static);
      if (btn) btn.hidden = true;
      return;
    }
    const user = img.dataset.user;
    const on = user === "on" || (auto && user !== "off" && !reducedMotion());
    const want = on ? img.dataset.anim : img.dataset.static;
    if (img.getAttribute("src") !== want) img.setAttribute("src", want);
    if (btn) {
      btn.hidden = false;
      btn.setAttribute("aria-pressed", String(on));
      btn.setAttribute("aria-label", on ? "Pausar" : "Animar");
      btn.textContent = on ? "❚❚" : "▶";
    }
  }

  function panelActive(img) {
    const host = img.closest(".catalog-host");
    return (!host || host.dataset.view !== "gallery") && img.closest(".tab-panel").classList.contains("active");
  }

  function wirePanels(el) {
    el.querySelectorAll(":scope > .tabs > .tab-panel").forEach((panel) => {
      const img = panel.querySelector(".thumb-frame img");
      if (!img) return;
      const btn = panel.querySelector(".thumb-play");
      const cap = panel.querySelector(".thumb-code");
      const base = { src: img.dataset.static, anim: img.dataset.anim || "",
        w: img.getAttribute("width"), h: img.getAttribute("height") };
      btn.addEventListener("click", () => {
        img.dataset.user = img.getAttribute("src") === img.dataset.anim ? "off" : "on";
        setPlaying(img, panelActive(img));
      });
      panel.querySelectorAll(".v-card").forEach((card) => {
        card.addEventListener("click", () => {
          const again = card.getAttribute("aria-pressed") === "true";
          panel.querySelectorAll(".v-card").forEach((c) => c.setAttribute("aria-pressed", "false"));
          const pick = again ? base : { src: card.dataset.src, anim: card.dataset.anim || "",
            w: card.dataset.w, h: card.dataset.h };
          img.dataset.static = pick.src;
          img.setAttribute("width", pick.w);
          img.setAttribute("height", pick.h);
          if (Number(pick.h) > Number(pick.w)) img.dataset.tall = ""; else delete img.dataset.tall;
          if (pick.anim) img.dataset.anim = pick.anim; else delete img.dataset.anim;
          img.setAttribute("src", pick.src);
          if (!again) card.setAttribute("aria-pressed", "true");
          cap.hidden = again;
          cap.querySelector("code").textContent = again ? "" : card.dataset.code;
          setPlaying(img, panelActive(img));
        });
      });
    });
  }

  // Loops play only where the eye is: the visible active panel of each host.
  function playThumbs(scope) {
    const hosts = scope && scope.classList && scope.classList.contains("catalog-host")
      ? [scope]
      : [...(scope || document).querySelectorAll(".catalog-host")];
    hosts.forEach((host) => {
      const tabsView = host.dataset.view !== "gallery";
      host.querySelectorAll(":scope > .tabs > .tab-panel .thumb-frame img").forEach((img) => {
        setPlaying(img, tabsView && img.closest(".tab-panel").classList.contains("active"));
      });
    });
  }

  const VIEW_KEY = "guia.catalog-view.";

  function showView(host, view, remember) {
    if (!host || !host.querySelector(":scope > .gallery")) return;
    host.dataset.view = view;
    host.querySelectorAll(":scope > .view-toggle button").forEach((b) => {
      b.setAttribute("aria-pressed", String(b.dataset.view === view));
    });
    if (remember) {
      try { w.localStorage.setItem(VIEW_KEY + host.id, view); } catch (e) { /* storage off */ }
    }
    playThumbs(host);
  }

  function savedView(host) {
    try { return w.localStorage.getItem(VIEW_KEY + host.id); } catch (e) { return null; }
  }

  function galleryCard(item) {
    const th = thumbOf(item);
    const hosts = item.hosts && item.hosts.length
      ? ` data-hosts="${esc(item.hosts.join(" "))}"`
      : "";
    const pic = th ? thumbImg(item, th, "lazy", true) : `<span class="g-none">sem prévia</span>`;
    const moves = th && th.anim ? " data-moves" : "";
    return `<button class="g-card" type="button" data-goto="${item.id}" data-kind="${item.kind}"${hosts}${moves}>
      <span class="g-img">${pic}</span><span class="g-name">${esc(item.name)}</span></button>`;
  }

  function wireGallery(el) {
    el.querySelectorAll(":scope > .view-toggle button").forEach((b) => {
      b.addEventListener("click", () => showView(el, b.dataset.view, true));
    });
    el.querySelectorAll(":scope > .gallery .g-card").forEach((card) => {
      const img = card.querySelector("img");
      card.addEventListener("mouseenter", () => setPlaying(img, true));
      card.addEventListener("mouseleave", () => setPlaying(img, false));
      card.addEventListener("focus", () => setPlaying(img, true));
      card.addEventListener("blur", () => setPlaying(img, false));
      card.addEventListener("click", () => {
        setPlaying(img, false);
        // Reading one card is not choosing Abas: only the toggle is remembered,
        // or the next visit opens this catalog without its gallery.
        showView(el, "tabs", false);
        const tab = el.querySelector(`:scope > .tabs > .tab-bar > .tab[data-tab="${card.dataset.goto}"]`);
        if (tab) tab.click();
        // The gallery just collapsed: bring the toggle + tab bar + panel to the top.
        el.querySelector(":scope > .view-toggle").scrollIntoView({ block: "start" });
      });
    });
    // Runs after the page's own tab handler (bubbling): the new panel is active.
    el.addEventListener("click", (e) => {
      if (e.target.closest(".tab-bar > .tab")) playThumbs(el);
    });
  }

  function fill(id, items) {
    const el = document.getElementById(id);
    if (!el) return;
    if (!items.length) {
      el.innerHTML = "";
      return;
    }
    const tabs = items.map((item, i) => {
      const on = i === 0 ? " active" : "";
      const hosts = item.hosts && item.hosts.length
        ? ` data-hosts="${esc(item.hosts.join(" "))}"`
        : "";
      return `<button class="tab${on}" type="button" data-tab="${item.id}" data-kind="${item.kind}"${hosts} data-search="${esc(item.search || "")}">${esc(item.name)}</button>`;
    }).join("");
    const panels = items.map((item, i) => renderPanel(item, i === 0)).join("");
    el.classList.add("catalog-host");
    const gallery = items.some(thumbOf)
      ? `<div class="view-toggle" role="group" aria-label="Ver o catálogo como">
          <button type="button" data-view="gallery">Galeria</button><button type="button" data-view="tabs">Abas</button></div>
        <div class="gallery">${items.map(galleryCard).join("")}</div>`
      : "";
    el.innerHTML = `${gallery}<div class="tabs catalog" data-tabs>
      <div class="tab-bar catalog">${tabs}</div>
      ${panels}
    </div>`;
    wirePanels(el);
    if (gallery) {
      wireGallery(el);
      const saved = savedView(el);
      showView(el, saved === "tabs" || saved === "gallery" ? saved : "gallery", false);
    }
  }

  w.ScenaGuideCatalogs = {
    LOOKS, STAMPS, TRANSIENTS, SPATIAL, POST, IMPACTS, BACKGROUNDS, FILTERS, fill,
    playThumbs, showView,
  };
})(window);
