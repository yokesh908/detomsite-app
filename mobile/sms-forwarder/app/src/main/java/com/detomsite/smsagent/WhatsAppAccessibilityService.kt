package com.detomsite.smsagent

import android.accessibilityservice.AccessibilityService
import android.os.Handler
import android.os.Looper
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo

/**
 * The "bot" half of the phone-side WhatsApp auto-sender.
 *
 * The foreground service opens WhatsApp with an order message pre-filled into a
 * chat. This service only acts when ALL of these hold:
 *
 *  - the bot is currently expecting a send ([AutoSendState.id] is set),
 *  - the foreground window is the WhatsApp conversation (not the chat list,
 *    not a story, not another app),
 *  - the on-screen text actually contains our pre-filled order token — so we
 *    never tap Send in a chat the user is typing into about something else.
 *
 * When all hold, it taps WhatsApp's Send button and tells the foreground
 * service to mark the notification as delivered.
 */
class WhatsAppAccessibilityService : AccessibilityService() {

    private val handler = Handler(Looper.getMainLooper())

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (event == null) return
        if (AutoSendState.id == null) return

        val pkg = event.packageName?.toString().orEmpty()
        if (pkg != "com.whatsapp" && pkg != "com.whatsapp.w4b") return
        if (event.eventType != AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED) return

        val className = event.className?.toString().orEmpty()
        if (!className.contains("Conversation")) return

        // Give WhatsApp a beat to render the pre-filled text box.
        handler.postDelayed({ trySend() }, 120)
    }

    private fun trySend() {
        val id = AutoSendState.id ?: return
        val root = rootInActiveWindow ?: return
        val token = AutoSendState.verifyToken ?: return
        if (!containsText(root, token)) return  // not our pre-filled message

        val send = findSendButton(root) ?: return
        if (send.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
            val payload = id
            AutoSendState.clear()
            handler.postDelayed({
                WhatsAppBotService.instance?.confirmSent(payload)
            }, 1500L)
        }
    }

    /** True when some on-screen node shows the pre-filled order token. */
    private fun containsText(node: AccessibilityNodeInfo, token: String): Boolean {
        val queue = ArrayDeque<AccessibilityNodeInfo>()
        queue.add(node)
        while (queue.isNotEmpty()) {
            val cur = queue.removeFirst()
            cur.text?.toString()?.let { if (it.contains(token)) return true }
            for (i in 0 until cur.childCount) {
                cur.getChild(i)?.let { queue.addLast(it) }
            }
        }
        return false
    }

    private fun findSendButton(root: AccessibilityNodeInfo): AccessibilityNodeInfo? {
        val queue = ArrayDeque<AccessibilityNodeInfo>()
        queue.add(root)
        while (queue.isNotEmpty()) {
            val cur = queue.removeFirst()
            val desc = cur.contentDescription?.toString().orEmpty()
            val viewId = cur.viewIdResourceName.orEmpty()
            if (desc.contains("send", ignoreCase = true) ||
                viewId.contains("send", ignoreCase = true)
            ) {
                return cur
            }
            for (i in 0 until cur.childCount) {
                cur.getChild(i)?.let { queue.addLast(it) }
            }
        }
        return null
    }

    override fun onInterrupt() {
        // Nothing to do — AutoSendState gates every tap, so interrupting is safe.
    }
}