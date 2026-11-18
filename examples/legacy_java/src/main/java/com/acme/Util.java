package com.acme;

import sun.misc.BASE64Encoder;
import javax.xml.bind.DatatypeConverter;

public class Util {
    // new Integer(5) in a comment must not be touched
    public Integer parse(String s) {
        return new Integer(s);
    }

    public String enc(byte[] b) {
        return new BASE64Encoder().encode(b);
    }

    public String hex(byte[] b) {
        return DatatypeConverter.printHexBinary(b);
    }

    @Override
    protected void finalize() {
    }
}
