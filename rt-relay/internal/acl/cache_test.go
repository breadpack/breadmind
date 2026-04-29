package acl

import (
	"sort"
	"testing"
)

func TestCache_HasAddRemove(t *testing.T) {
	c := NewCacheFromSlice([]string{"a", "b"})
	if !c.Has("a") || !c.Has("b") || c.Has("c") {
		t.Fatal("initial Has wrong")
	}
	if !c.Add("c") || c.Add("a") {
		t.Fatal("Add return wrong")
	}
	if !c.Remove("b") || c.Remove("nope") {
		t.Fatal("Remove return wrong")
	}
}

func TestCache_Replace(t *testing.T) {
	c := NewCacheFromSlice([]string{"a", "b", "c"})
	added, removed := c.Replace([]string{"b", "c", "d"})
	sort.Strings(added)
	sort.Strings(removed)
	if len(added) != 1 || added[0] != "d" {
		t.Fatalf("added=%v", added)
	}
	if len(removed) != 1 || removed[0] != "a" {
		t.Fatalf("removed=%v", removed)
	}
	if !c.Has("d") || c.Has("a") {
		t.Fatal("set not swapped")
	}
}
