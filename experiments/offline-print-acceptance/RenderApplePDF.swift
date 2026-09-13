// SPDX-License-Identifier: MIT
// Local synthetic PDF comparison using Apple's CoreGraphics and ImageIO.
import Foundation
import CoreGraphics
import ImageIO

let args=CommandLine.arguments
guard args.count==3,let document=CGPDFDocument(URL(fileURLWithPath:args[1]) as CFURL) else {exit(64)}
for index in 1...document.numberOfPages {
    guard let page=document.page(at:index) else {exit(65)}
    let box=page.getBoxRect(.mediaBox),width=Int(ceil(box.width)),height=Int(ceil(box.height))
    guard let context=CGContext(data:nil,width:width,height:height,bitsPerComponent:8,
                                bytesPerRow:width*4,space:CGColorSpaceCreateDeviceRGB(),
                                bitmapInfo:CGImageAlphaInfo.premultipliedLast.rawValue) else {exit(66)}
    context.setFillColor(CGColor(red:1,green:1,blue:1,alpha:1))
    context.fill(CGRect(x:0,y:0,width:width,height:height))
    context.drawPDFPage(page)
    guard let image=context.makeImage(),let output=CGImageDestinationCreateWithURL(
        URL(fileURLWithPath:"\(args[2])-\(index).png") as CFURL,"public.png" as CFString,1,nil) else {exit(67)}
    CGImageDestinationAddImage(output,image,nil)
    if !CGImageDestinationFinalize(output){exit(68)}
}
