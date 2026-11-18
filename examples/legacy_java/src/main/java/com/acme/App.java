package com.acme;

import com.acme.Util;

public class App {
    public static void main(String[] args) {
        Util u = new Util();
        System.out.println(u.parse("42"));
        Thread t = new Thread(() -> {});
        t.start();
        t.stop();
    }
}
