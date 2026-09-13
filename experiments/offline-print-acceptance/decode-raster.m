/* SPDX-License-Identifier: MIT
 * Read an offline Apple Raster stream, measure pixels, and save small PNGs.
 * There is no CUPS connection, backend, queue operation, or device I/O here.
 */
#import <Foundation/Foundation.h>
#import <CoreGraphics/CoreGraphics.h>
#import <ImageIO/ImageIO.h>
#include <CommonCrypto/CommonDigest.h>
#include <cups/raster.h>
#include <fcntl.h>
#include <unistd.h>

static NSString *hex(const unsigned char *bytes, size_t count) {
    NSMutableString *s = [NSMutableString stringWithCapacity:count*2];
    for (size_t i=0; i<count; ++i) [s appendFormat:@"%02x", bytes[i]];
    return s;
}

int main(int argc, char **argv) { @autoreleasepool {
    if (argc != 4) return 64;
    int fd = open(argv[1], O_RDONLY);
    if (fd < 0) return 1;
    cups_raster_t *r = cupsRasterOpen(fd, CUPS_RASTER_READ);
    if (!r) { close(fd); return 2; }
    NSMutableArray *pages = [NSMutableArray array];
    cups_page_header2_t h;
    NSUInteger number=0;
    while (cupsRasterReadHeader2(r, &h)) {
        if (h.cupsWidth < 1 || h.cupsHeight < 1 || h.cupsWidth > 20000 ||
            h.cupsHeight > 20000 || h.cupsBitsPerPixel != 8 ||
            h.cupsBitsPerColor != 8 || h.cupsNumColors != 1 ||
            h.cupsBytesPerLine != h.cupsWidth) return 3;
        unsigned char *row = malloc(h.cupsBytesPerLine);
        if (!row) return 4;
        unsigned scale=4, tw=(h.cupsWidth+scale-1)/scale,
                 th=(h.cupsHeight+scale-1)/scale;
        unsigned char *thumb=malloc((size_t)tw*th);
        if (!thumb) return 5;
        memset(thumb, 255, (size_t)tw*th);
        unsigned minx=h.cupsWidth, miny=h.cupsHeight, maxx=0, maxy=0;
        uint64_t dark=0;
        CC_SHA256_CTX sha; CC_SHA256_Init(&sha);
        for (unsigned y=0; y<h.cupsHeight; ++y) {
            if (cupsRasterReadPixels(r,row,h.cupsBytesPerLine)!=h.cupsBytesPerLine) return 6;
            CC_SHA256_Update(&sha,row,h.cupsBytesPerLine);
            for (unsigned x=0; x<h.cupsWidth; ++x) if (row[x]<128) {
                ++dark; if(x<minx)minx=x; if(x>maxx)maxx=x;
                if(y<miny)miny=y; if(y>maxy)maxy=y;
            }
            if (y%scale==0) for (unsigned x=0; x<h.cupsWidth; x+=scale)
                thumb[(size_t)(y/scale)*tw+x/scale]=row[x];
        }
        unsigned char digest[CC_SHA256_DIGEST_LENGTH]; CC_SHA256_Final(digest,&sha);
        free(row);
        NSString *name=[NSString stringWithFormat:@"page-%02lu.png",(unsigned long)++number];
        NSString *path=[[NSString stringWithUTF8String:argv[2]] stringByAppendingPathComponent:name];
        CGDataProviderRef provider=CGDataProviderCreateWithData(NULL,thumb,(size_t)tw*th,NULL);
        CGColorSpaceRef gray=CGColorSpaceCreateDeviceGray();
        CGImageRef image=CGImageCreate(tw,th,8,8,tw,gray,(CGBitmapInfo)kCGImageAlphaNone,provider,NULL,false,kCGRenderingIntentDefault);
        CGImageDestinationRef dest=CGImageDestinationCreateWithURL((__bridge CFURLRef)[NSURL fileURLWithPath:path],CFSTR("public.png"),1,NULL);
        if (!image || !dest) return 7;
        CGImageDestinationAddImage(dest,image,NULL);
        if (!CGImageDestinationFinalize(dest)) return 8;
        CFRelease(dest); CGImageRelease(image); CGColorSpaceRelease(gray);
        CGDataProviderRelease(provider); free(thumb);
        [pages addObject:@{@"page":@(number),@"width":@(h.cupsWidth),@"height":@(h.cupsHeight),
            @"dpi":@[@(h.HWResolution[0]),@(h.HWResolution[1])],
            @"bits_per_pixel":@(h.cupsBitsPerPixel),@"color_space":@(h.cupsColorSpace),
            @"num_copies_header":@(h.NumCopies),@"collate_header":@(h.Collate),
            @"orientation_header":@(h.Orientation),@"page_size_points":@[@(h.cupsPageSize[0]),@(h.cupsPageSize[1])],
            @"dark_pixels_below_128":@(dark),@"dark_bounds_inclusive":@[@(minx),@(miny),@(maxx),@(maxy)],
            @"pixel_sha256":hex(digest,sizeof digest),@"thumbnail":name,
            @"thumbnail_size":@[@(tw),@(th)],@"thumbnail_sampling":@"one pixel every four; preview/OCR only; geometry measured at full resolution"}];
    }
    cupsRasterClose(r); close(fd);
    NSData *json=[NSJSONSerialization dataWithJSONObject:@{@"pages":pages,@"page_count":@(number)} options:NSJSONWritingPrettyPrinted error:NULL];
    if (![json writeToFile:[NSString stringWithUTF8String:argv[3]] atomically:YES]) return 9;
    return number ? 0 : 10;
} }
