pe32powerpy_pub
===============

FIXME.. needs docs


-----------------------------------
Setting up a read-only Raspberry Pi
-----------------------------------

https://raspberrypi.stackexchange.com/questions/78232/install-base-raspbian-from-repository-not-using-an-image
https://wiki.debian.org/ArmHardFloatChroot
SOURCES: deb http://raspbian.raspberrypi.org/raspbian buster main rpi firmware # contrib non-free

::

    # grep '^[^#]' /boot/config.txt
    kernel=vmlinuz-4.9.0-6-rpi2
    initrd=initrd.img-4.9.0-6-rpi2 followkernel

    # cat /boot/cmdline.txt
    console=tty1 root=/dev/mmcblk0p2 rootfstype=ext4 elevator=deadline fsck.repair=yes rootwait fastboot noswap ro

    # cat /etc/fstab
    /dev/mmcblk0p1  /boot    vfat    defaults,ro          0 2
    /dev/mmcblk0p2  /        ext4    defaults,ro,noatime  0 1

    tmpfs /tmp             tmpfs nosuid,nodev  0 0
    tmpfs /var/lib/dhcp    tmpfs nosuid,nodev  0 0
    tmpfs /var/lib/systemd tmpfs nosuid,nodev  0 0
    tmpfs /var/lock        tmpfs nosuid,nodev  0 0
    tmpfs /var/log         tmpfs nosuid,nodev  0 0
    tmpfs /var/spool       tmpfs nosuid,nodev  0 0
    tmpfs /var/tmp         tmpfs nosuid,nodev  0 0

# Hint: From now on use sudo logread to check your system logs. (Or journalctl of course.)
https://medium.com/@andreas.schallwig/how-to-make-your-raspberry-pi-file-system-read-only-raspbian-stretch-80c0f7be7353
https://medium.com/swlh/make-your-raspberry-pi-file-system-read-only-raspbian-buster-c558694de79

----

::

    root@framboos(rw):~# cat /etc/systemd/system/networking.service.d/override.conf
    [Service]
    ExecStartPre=-sh -c 'find /var/lib/dhcp.static/ -type f -print0 | xargs -0 --no-run-if-empty -IX cp -a X /var/lib/dhcp/'
    ExecStartPre=/usr/local/bin/auto-ifaces
    ExecStopPost=-sh -c 'mount -o remount,rw /; find /var/lib/dhcp/ -type f -print0 | xargs -0 --no-run-if-empty -IX cp -a X /var/lib/dhcp.static/'

::

    #!/bin/sh -x
    #
    # Called from /etc/systemd/system/networking.service.d/override.conf:
    #   ExecStartPre=/usr/local/bin/auto-ifaces
    #

    /bin/rm /etc/network/interfaces
    for iface in $(
            /sbin/ip link | /bin/sed -e '/^[0-9]/!d;s/^[0-9]*: //;s/:.*//'); do
        if test $iface = lo; then
            printf 'auto lo\niface lo inet loopback\n' \
              >>/etc/network/interfaces
    #    elif test $iface = enp9s0 -o $iface = enp9s0f0; then
    #        # physically broken interface
    #        # [   19.191416] sky2 0000:09:00.0: enp9s0f0: phy I/O error
    #        # [   19.191442] sky2 0000:09:00.0: enp9s0f0: phy I/O error
    #        /sbin/ip link set down $iface
        else
            # ethtool not needed with dongle anymore.
            #/sbin/ethtool -s $iface speed 100 duplex full
            printf 'auto %s\niface %s inet dhcp\n' $iface $iface \
              >>/etc/network/interfaces
        fi
    done

    true

::

    diff --git a/dhcp/dhclient.conf b/dhcp/dhclient.conf
    index b85301b..218919c 100644
    --- a/dhcp/dhclient.conf
    +++ b/dhcp/dhclient.conf
    @@ -22,6 +22,7 @@ request subnet-mask, broadcast-address, time-offset, routers,
     #send dhcp-client-identifier 1:0:a0:24:ab:fb:9c;
     #send dhcp-lease-time 3600;
     #supersede domain-name "fugue.com home.vix.com";
    +append domain-name-servers 1.1.1.1, 8.8.8.8;
     #prepend domain-name-servers 127.0.0.1;
     #require subnet-mask, domain-name-servers;
     #timeout 60;
    diff --git a/resolv.conf b/resolv.conf
    deleted file mode 100644
    index 87af862..0000000
    --- a/resolv.conf
    +++ /dev/null
    @@ -1 +0,0 @@
    -nameserver SOMETHING
    diff --git a/resolv.conf b/resolv.conf
    new file mode 120000
    index 0000000..c0b2e5e
    --- /dev/null
    +++ b/resolv.conf
    @@ -0,0 +1 @@
    +/run/resolv.conf
