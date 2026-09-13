// SPDX-License-Identifier: MIT
// Read-only public ImageCaptureCore identity diagnostic; never opens a session.
#import <Foundation/Foundation.h>
#import <ImageCaptureCore/ImageCaptureCore.h>
@interface Observer : NSObject <ICDeviceBrowserDelegate>
@end
@implementation Observer
- (void)deviceBrowser:(ICDeviceBrowser*)b didAddDevice:(ICDevice*)d moreComing:(BOOL)more {
    if (![d.name containsString:@"3025"]) return;
    NSDictionary *info=@{@"name":d.name?:@"", @"uuid":d.UUIDString?:@"", @"persistent_id":d.persistentIDString?:@"", @"transport":d.transportType?:@"", @"serial":d.serialNumberString?:@"", @"location":d.locationDescription?:@"", @"class":NSStringFromClass(d.class)};
    NSData *json=[NSJSONSerialization dataWithJSONObject:info options:NSJSONWritingSortedKeys error:nil];
    puts([[NSString alloc] initWithData:json encoding:NSUTF8StringEncoding].UTF8String);
}
- (void)deviceBrowser:(ICDeviceBrowser*)b didRemoveDevice:(ICDevice*)d moreGoing:(BOOL)more {}
@end
int main(void) { @autoreleasepool {
    Observer *observer=[Observer new]; ICDeviceBrowser *browser=[ICDeviceBrowser new];
    browser.delegate=observer;
    browser.browsedDeviceTypeMask = (ICDeviceTypeMask)(ICDeviceTypeMaskScanner | ICDeviceLocationTypeMaskLocal | ICDeviceLocationTypeMaskBonjour);
    [browser start]; [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:10]]; [browser stop];
} return 0; }
