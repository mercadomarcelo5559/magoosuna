"""prospectos.json -> Prospectos.xlsx (pestaña "Prospectos", mismas columnas que la hoja de Google)."""
import json
import sys

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

filas = json.load(open(sys.argv[1], encoding="utf-8"))
wb = Workbook()
ws = wb.active
ws.title = "Prospectos"
cols = list(filas[0].keys())
ws.append(cols)
for f in filas:
    ws.append([f[c] for c in cols])
for c in ws[1]:
    c.font = Font(bold=True, color="FFFFFF")
    c.fill = PatternFill("solid", fgColor="0F766E")
anchos = {"ID": 14, "Nota": 6, "Clínica": 34, "Motivo": 50, "Señales": 50, "Mensaje": 70, "Horario": 40, "Dirección": 40}
for i, c in enumerate(cols, 1):
    letra = ws.cell(1, i).column_letter
    ws.column_dimensions[letra].width = anchos.get(c, 22)
    for fila in ws.iter_rows(min_row=2, min_col=i, max_col=i):
        for cel in fila:
            cel.alignment = Alignment(wrap_text=c in ("Mensaje", "Motivo", "Señales", "Horario"), vertical="top")
            if c in ("Abrir en WhatsApp", "Google Maps", "Web", "Demo") and cel.value:
                cel.hyperlink = cel.value
                cel.font = Font(color="0563C1", underline="single")
                if c == "Abrir en WhatsApp":
                    cel.value = "Abrir en WhatsApp"
ws.freeze_panes = "D2"
ws.auto_filter.ref = ws.dimensions
wb.save(sys.argv[2])
