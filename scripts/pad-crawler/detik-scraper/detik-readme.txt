https://news.detik.com
https://hot.detik.com
https://finance.detik.com
https://inet.detik.com (Tidak sama class untuk selectornya)
https://sport.detik.com
https://oto.detik.com
https://travel.detik.com
... Masih kurang lengkap

# To do selanjutnya sepertinya membuat penanganan khusus untuk tiap-tiap web di detik.com misal tags bagaimana, misal 20.detik.com bagaiamana, dstnya

Cara lihat attribute
# ambil elemen pertama sebagai contoh
el = links.nth(0)

# 1 daftar nama atribut
attr_names = el.evaluate("node => node.getAttributeNames()")
print("Attribute names:", attr_names)

# 2 nama + nilainya
attr_map = el.evaluate("""
node => Object.fromEntries(
    node.getAttributeNames().map(name => [name, node.getAttribute(name)])
)
""")
print("Attribute map:", attr_map)

# 3 lihat HTML mentah elemennya
html = el.evaluate("node => node.outerHTML")
print(html)