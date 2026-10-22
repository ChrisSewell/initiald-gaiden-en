import sys,struct
from PIL import Image
d=open(sys.argv[1],"rb").read(); out=sys.argv[2]; ids=list(map(int,sys.argv[3:]))
def tile(t):
    im=Image.new("L",(8,8),255)
    if t<128:
        b=d[0x14000+t*16:0x14010+t*16]
        for y in range(8):
            v=b[2*y]|b[2*y+1]
            for x in range(8):
                if (v>>(7-x))&1: im.putpixel((x,y),0)
    elif t in (0x80,0x81,0x82,0x83,0x84,0x85):
        for i in range(8):
            if t in (0x81,0x80,0x82): im.putpixel((i,4),0)
            if t in (0x84,0x85): im.putpixel((i,4),0)
            if t in (0x83,0x80,0x82,0x84,0x85): im.putpixel((4,i),0)
    else:
        for i in range(0,8,2): im.putpixel((i,i),128)
    return im
imgs=[]
for k in ids:
    p=struct.unpack_from("<H",d,0x10000+2*k)[0]; off=0x10000+p-0x4000
    w,h=d[off+1]+1,d[off+2]+1
    im=Image.new("L",(w*8,h*8),255)
    for y in range(h):
        for x in range(w): im.paste(tile(d[off+3+y*w+x]),(x*8,y*8))
    imgs.append(im)
W=max(i.width for i in imgs)+8; H=sum(i.height+8 for i in imgs)
sheet=Image.new("L",(W*2 if len(imgs)>1 else W,1),255)
cols=2; colh=[0,0]; pos=[]
for i in imgs:
    c=colh.index(min(colh)); pos.append((c*W,colh[c])); colh[c]+=i.height+8
sheet=Image.new("L",(W*cols,max(colh)),255)
for i,p in zip(imgs,pos): sheet.paste(i,p)
sheet.resize((sheet.width*3,sheet.height*3),Image.NEAREST).save(out)
