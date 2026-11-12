// PaperSearch's notification host. No network, browser launching or input hooks.
// Rebuild with build_macos_notifier.py; the universal binary ships with the package.
#import <AppKit/AppKit.h>
#import <CoreServices/CoreServices.h>

static void emit(NSDictionary *event) {
    NSData *json = [NSJSONSerialization dataWithJSONObject:event options:0 error:nil];
    if (json) {
        NSFileHandle *out = NSFileHandle.fileHandleWithStandardOutput;
        [out writeData:json];
        [out writeData:[@"\n" dataUsingEncoding:NSUTF8StringEncoding]];
    }
}

@interface PaperSearchNotifier : NSObject <NSApplicationDelegate, NSUserNotificationCenterDelegate>
@property(copy) NSString *instanceID;
@end

@implementation PaperSearchNotifier
- (void)applicationDidFinishLaunching:(NSNotification *)note {
    self.instanceID = NSUUID.UUID.UUIDString;
    NSUserNotificationCenter.defaultUserNotificationCenter.delegate = self;
    emit(@{@"event": @"ready", @"bundle_id": NSBundle.mainBundle.bundleIdentifier});
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{
        // One bounded JSON command per line. EOF means the capsule is gone.
        char buffer[65536];
        while (fgets(buffer, sizeof(buffer), stdin)) {
            @autoreleasepool {
                if (!strchr(buffer, '\n')) break;
                NSData *data = [NSData dataWithBytes:buffer length:strlen(buffer)];
                id command = [NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
                if (![command isKindOfClass:NSDictionary.class]) continue;
                dispatch_async(dispatch_get_main_queue(), ^{ [self handle:command]; });
            }
        }
        dispatch_async(dispatch_get_main_queue(), ^{ [NSApp terminate:nil]; });
    });
}
- (void)clearOwnNotifications {
    NSUserNotificationCenter *center = NSUserNotificationCenter.defaultUserNotificationCenter;
    for (NSUserNotification *notification in center.deliveredNotifications) {
        if ([notification.userInfo[@"owner"] isEqual:self.instanceID])
            [center removeDeliveredNotification:notification];
    }
}
- (void)handle:(NSDictionary *)command {
    NSUserNotificationCenter *center = NSUserNotificationCenter.defaultUserNotificationCenter;
    NSString *action = command[@"action"];
    if ([action isEqual:@"clear"]) {
        [self clearOwnNotifications];
        return;
    }
    if (![action isEqual:@"notify"]) return;
    for (NSString *key in @[@"title", @"body", @"current", @"run_id"])
        if (![command[key] isKindOfClass:NSString.class]) return;
    NSUserNotification *notification = [NSUserNotification new];
    notification.title = command[@"title"];
    notification.informativeText = command[@"body"];
    notification.identifier = NSUUID.UUID.UUIDString;
    notification.userInfo = @{@"current": command[@"current"], @"run_id": command[@"run_id"], @"owner": self.instanceID};
    [center deliverNotification:notification];
}
- (BOOL)userNotificationCenter:(NSUserNotificationCenter *)center shouldPresentNotification:(NSUserNotification *)notification {
    return YES;
}
- (void)userNotificationCenter:(NSUserNotificationCenter *)center didDeliverNotification:(NSUserNotification *)notification {
    emit(@{@"event": @"delivered", @"current": notification.userInfo[@"current"],
           @"run_id": notification.userInfo[@"run_id"]});
}
- (void)userNotificationCenter:(NSUserNotificationCenter *)center didActivateNotification:(NSUserNotification *)notification {
    if (![notification.userInfo[@"owner"] isEqual:self.instanceID]) return;
    // Transfer this user-initiated activation to the capsule. Its normal action
    // validates the current run before selecting/restoring the task's browser.
    NSRunningApplication *capsule = [NSRunningApplication runningApplicationWithProcessIdentifier:getppid()];
    if (capsule) {
        if (@available(macOS 14.0, *)) {
            [NSApp yieldActivationToApplication:capsule];
            [capsule activateFromApplication:NSRunningApplication.currentApplication options:0];
        } else {
            [capsule activateWithOptions:NSApplicationActivateIgnoringOtherApps];
        }
    }
    emit(@{@"event": @"clicked", @"current": notification.userInfo[@"current"],
           @"run_id": notification.userInfo[@"run_id"]});
    [center removeDeliveredNotification:notification];
}
- (void)applicationWillTerminate:(NSNotification *)note {
    [self clearOwnNotifications];
}
@end

int main(void) {
    @autoreleasepool {
        // Register only our own bundle so Notification Center resolves its icon/name.
        LSRegisterURL((__bridge CFURLRef)NSBundle.mainBundle.bundleURL, true);
        [NSApplication sharedApplication];
        [NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];
        PaperSearchNotifier *delegate = [PaperSearchNotifier new];
        NSApp.delegate = delegate;
        [NSApp run];
    }
    return 0;
}
