import markdown
from fpdf import FPDF

md_file = "E:/development_brahma/brahma-cos/BRAHMA_COS_PROJECT_DOCUMENTATION.md"
pdf_file = "E:/development_brahma/brahma-cos/BRAHMA_COS_PROJECT_DOCUMENTATION.pdf"

with open(md_file, "r", encoding="utf-8") as f:
    text = f.read()

# Clean up unsupported unicode characters for fpdf standard fonts
text = text.replace("```text", "```").replace("```python", "```")
text = text.replace("→", "->").replace("—", "-")
html = markdown.markdown(text, extensions=['tables'])

class PDF(FPDF):
    def footer(self):
        self.set_y(-15)
        self.set_font('helvetica', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()}', align='C')

pdf = PDF()
pdf.add_page()
pdf.set_font("helvetica", size=10)
try:
    pdf.write_html(html)
    pdf.output(pdf_file)
    print("PDF generation complete.")
except Exception as e:
    print(f"Error: {e}")
